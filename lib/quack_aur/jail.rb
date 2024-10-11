# frozen_string_literal: true

require 'fileutils'
require 'tmpdir'
require_relative 'helper'

module QuackAur
  class Jail
    def initialize(package, options = {})
      @tmpdir = nil
      @origindir = Dir.pwd
      @force = options[:force]
      @dry_run = options[:dry_run]
      @main_package = package
      @built_packages = []
    end

    def build
      if @main_package['BuiltPackages'].any? && !@force
        return @main_package['BuiltPackages']
      end
      return [] unless handle_dependencies

      build_in_tmpdir @main_package
      @built_packages
    end

    def install
      dependencies = @built_packages - @main_package['BuiltPackages']
      deps_install = %w[pacman -U --asdeps] + dependencies
      main_install = %w[pacman -U] + @main_package['BuiltPackages']
      if @dry_run
        puts "sudo #{deps_install.join(' ')}" if dependencies.any?
        puts "sudo #{main_install.join(' ')}"
        puts "sudo cp #{@built_packages.join(' ')} /var/cache/pacman/pkg/"
        puts "rm #{@built_packages.join(' ')}"
      else
        system(*QuackAur.sudo_wrapper(deps_install)) if dependencies.any?
        system(*QuackAur.sudo_wrapper(main_install))
        cp_cmd = %w[cp /var/cache/pacman/pkg/]
        cp_cmd.insert(1, @built_packages)
        system(*QuackAur.sudo_wrapper(cp_cmd.flatten))
        FileUtils.rm(@built_packages)
      end
    end

    private

    def buildable_packages(package)
      QuackAur.capture_no_err(
        %w[makepkg --packagelist]
      ).filter_map do |tarball_path|
        tarball = File.basename(tarball_path, '.pkg.tar.zst')
        next unless tarball.end_with?('-any', "-#{package['CARCH']}")

        "#{tarball}.pkg.tar.zst"
      end
    end

    def build_dry_run
      puts 'makepkg -sr --skipinteg'
    end

    def build_current
      system('makepkg', '-sr', '--skipinteg')
    end

    def check_package_integrity
      return if system('makepkg', '--verifysource')

      raise I18n.t('jail.integrity_failure')
    end

    def user_accepts_dependencies(dependencies)
      QuackAur.print_log('jail.dependencies_list')
      QuackAur.print_result(dependencies.map(&:name).join('  '))
      check = QuackAur.ask_question(
        'jail.validate_dependency', choices: '[y/N/q]'
      )
      exit if check == 'q'

      check == 'y'
    end

    def user_verification
      QuackAur.print_log('jail.user_verification.message')
      check = QuackAur.ask_question(
        'jail.user_verification.question', choices: '[y/N/q]'
      )
      exit if check == 'q'

      check == 'y'
    end

    def handle_dependencies
      # Begin the lookup with self to avoid obvious dependency cycles
      dependencies = @main_package.extract_dependencies([@main_package])
      dependencies.shift # Remove self from it

      return true if dependencies.empty?
      return false unless user_accepts_dependencies(dependencies)

      dependencies.each { |package| build_in_tmpdir package }
    end

    def close_tmpdir
      return unless @tmpdir && Dir.exist?(@tmpdir)

      Dir.chdir @origindir
      FileUtils.remove_entry_secure @tmpdir
      @tmpdir = nil
    end

    def switch_to_tmpdir(package)
      @origindir = Dir.pwd
      @tmpdir = Dir.mktmpdir 'quack_aur_'
      success = system(
        'git', 'clone',
        "https://aur.archlinux.org/#{package['PackageBase']}.git",
        @tmpdir
      )
      raise I18n.t('jail.clone_failure', package: package.name) unless success

      Dir.chdir @tmpdir

      unless File.exist?('PKGBUILD')
        raise I18n.t('jail.pkgbuild_missing', package: package.name)
      end

      QuackAur.print_log(
        'jail.ready_to_build',
        package: Rainbow(package.name).yellow.bold,
        tmpdir: @tmpdir
      )
    end

    def build_in_tmpdir(package)
      switch_to_tmpdir package
      return unless user_verification

      # Run check in current environment to handle all possible requirements
      # (gpg keys...). We check this early because neither docker or chroot
      # build are able to do it in their striped down environments. It's
      # interesting too to check that everything will be fine in dry run.
      check_package_integrity

      if @dry_run
        build_dry_run
        built_packages = buildable_packages(package)

      else
        build_current
        built_packages = buildable_packages(package).filter_map do |file|
          next unless File.exist?(file)

          dest_file = File.expand_path file, @origindir
          FileUtils.mv file, dest_file, force: true, verbose: true, secure: true
          file
        end
        raise I18n.t('jail.no_package_built') if built_packages.empty?
      end

      package['BuiltPackages'] = built_packages
      @built_packages += built_packages
    rescue RuntimeError => error
      QuackAur.print_error error, skip_translate: true
    ensure
      close_tmpdir
    end
  end
end
