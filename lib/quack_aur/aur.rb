# frozen_string_literal: true

require_relative 'helper'
require_relative 'package'
require_relative 'jails/chroot'
require_relative 'jails/docker'

module QuackAur
  # Permit operation on AUR Packages
  class Aur
    def initialize(options)
      @color = QuackAur.setup_color_mode options.delete(:color)
      @jail = options.delete(:jail) || :docker
      @options = options
    end

    def search(packages)
      result = Package.search(packages)
      return if result.empty?

      result.each do |package|
        next unless @options[:with_devel] || !Package.devel?(package.name)

        display_name = QuackAur.color_package(package)
        puts "#{display_name}\n    #{package.description}"
      end
    end

    def info(packages)
      info_fields = %w[Name Version Description URL License Provides Depends
                       MakeDepends Conflicts Maintainer LastModified OutOfDate
                       NumVotes Popularity AurPage Keywords].freeze
      packages.each do |package_name|
        package = Package.details(package_name)
        next unless package

        info_fields.each { info_line(_1, package) }

        next unless package.local?

        tarballs = package['BuiltPackages']
        next unless tarballs.any?

        QuackAur.print_log(
          'build.package_already_built',
          name: package.name,
          packages: tarballs.join('  ')
        )
      end
    end

    def list
      system('pacman', '-Qm')
    end

    def upgrade
      pkg_idx = 0
      installed_packages = `pacman --color=never -Qqm`.chomp.split("\n")
      packages_to_upgrade = installed_packages.filter_map do |package_name|
        package = Package.details(package_name)
        next unless package
        next unless @options[:with_devel] || !Package.devel?(package.name)
        next unless package.upgrade?

        message = format(
          '[%<index>i] %<package>s - %<curver>s - %<upver>s',
          index: (pkg_idx += 1),
          package: Rainbow(package.name).bold,
          curver: Rainbow(package['LocalVersion']).red,
          upver: Rainbow(package.version).green
        )
        puts message
        package
      end
      do_upgrade packages_to_upgrade
    end

    def install(packages)
      packages.each do |package_name|
        package = Package.details(package_name)
        next unless package

        do_install package
      end
    end

    private

    def do_install(package)
      jail_klass = Kernel.const_get("::QuackAur::#{@jail.capitalize}")
      jail = jail_klass.new(package, @options)
      built_packages = jail.build
      return if built_packages.empty?

      QuackAur.print_log('build.built_list', new_line: true)
      QuackAur.print_result built_packages.join('  ')
      puts ''
      check = QuackAur.ask_question('build.install_question', choices: '[y/N]')
      if check == 'y'
        jail.install
      else
        QuackAur.print_result('build.no_install')
      end
    end

    def do_upgrade(packages)
      return if packages.empty?

      number = packages.length
      if number == 1
        choices = '[Y/n]'
      else
        choices = "[1…#{number}/A/q]"
      end
      what = QuackAur.ask_question(
        'build.what_to_upgrade',
        choices: choices, number: number
      )
      return if %w[n q].include?(what)

      unless what == '' || %w[a y].include?(what)
        packages = what.split.map { packages[_1.to_i - 1] }
      end
      packages.each { do_install _1 }
    end

    def convert_value_array(value, title)
      if %w[Depends MakeDepends].include?(title)
        value.map! do |package|
          if Package.local?(package)
            Rainbow(package).underline
          else
            package
          end
        end
      end
      return '--' if value.empty?

      value.join(' ')
    end

    def convert_value_time(value, title)
      value = Trsl.l(value)
      return value unless title == 'OutOfDate'

      Rainbow(
        Trsl['info.outdated_since', date: value]
      ).red.bold
    end

    def info_line(title, data)
      value = data[title] || '--'
      convert_method = :"convert_value_#{value.class.name.downcase}"
      if private_methods.include?(convert_method)
        value = send(convert_method, value, title)
      end
      label = Trsl["info.info_line.#{title.downcase}"].ljust(25)
      label = Rainbow("#{label}:").bold
      puts "#{label} #{value}"
    end
  end
end
