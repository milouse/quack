# frozen_string_literal: true

require 'open3'
require 'rainbow'
require_relative 'i18n'

# Various utilitary methods
module QuackAur
  def self.setup_color_mode(mode)
    mode ||= :auto
    return mode if mode == :auto

    Rainbow.enabled = mode == :always
    mode
  end

  def self.print_log(message, opts = {})
    new_line = opts.delete(:new_line)
    message = I18n.t message, **opts
    prefix = Rainbow('::').blue.bold
    prefix = "\n#{prefix}" if new_line
    puts "#{prefix} #{message}"
  end

  def self.print_result(message, opts = {})
    prefix = Rainbow('==>').green.bold
    translated = I18n.t(message, **opts)
    translated = message if translated.start_with?('Translation missing:')
    message = Rainbow(translated).bold
    puts "#{prefix} #{message}"
  end

  def self.print_warning(message, opts = {})
    prefix = Rainbow(I18n.t('warning')).yellow.bold
    message = I18n.t message, **opts
    warn "#{prefix} #{message}"
  end

  def self.print_error(message, opts = {})
    prefix = Rainbow(I18n.t('error')).red.bold
    message = I18n.t(message, **opts) unless opts.delete(:skip_translate)
    warn "#{prefix} #{message}"
  end

  def self.ask_question(message, opts = {})
    choices = opts.delete(:choices)
    message = [
      Rainbow('::').blue.bold,
      Rainbow(I18n.t(message, **opts)).bold,
      choices,
      '> '
    ].compact
    print message.join(' ')
    $stdin.gets.chomp.downcase
  end

  def self.color_package(package)
    prefix = Rainbow('aur/').magenta.bold
    package_name = Rainbow(package.name).bold
    package_version = package.version
    colored_name = [
      "#{prefix}#{package_name}",
      Rainbow(package_version).green.bold
    ]
    if package.local?
      if package_version == package['LocalVersion']
        installed_label = I18n.t('info.installed')
      else
        installed_label = I18n.t(
          'info.installed_version',
          version: package['LocalVersion']
        )
      end
      colored_name << Rainbow(format('[%s]', installed_label)).cyan.bold
    end
    if package.outdated?
      outlabel = format('[%s]', I18n.t('info.outdated'))
      colored_name << Rainbow(outlabel).red.bold
    end
    colored_name.join(' ')
  end

  def self.capture_no_err(command)
    output, = Open3.capture2(
      { 'LANG' => 'C' }, *command, err: File::NULL
    )
    output.chomp.split("\n")
  end

  # This method is usefull to just get the exit status of a command and
  # discarding any output
  def self.system?(*command)
    binary = command.first
    command = binary if command.length == 1 && binary.is_a?(Array)

    system(*command, %i[out err] => File::NULL)
  end

  def self.which(executable)
    system?('which', executable)
  end

  def self.sudo_guard?(binary)
    if binary && %w[docker pacman].include?(binary)
      # Some people authorize docker or pacman in their sudoers
      guard = %W[sudo -n #{binary} --version]
    else
      guard = %w[sudo -n true]
    end
    system?(guard)
  end

  def self.sudo_wrapper(command)
    binary = command.first
    command.insert(0, 'sudo')
    return command if sudo_guard?(binary)

    QuackAur.print_warning('sudo_warning')
    $stdin.gets # wait for user input
    command
  end
end
