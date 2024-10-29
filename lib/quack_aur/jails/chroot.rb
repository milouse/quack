# frozen_string_literal: true

require_relative '../helper'
require_relative '../jail'

module QuackAur
  # Isolate package building in a docker container
  class Chroot < Jail
    def build
      unless QuackAur.which('mkarchroot')
        QuackAur.print_error(
          'jail.missing_dependency',
          package: 'devtools', jail: 'chroot'
        )
        return []
      end
      super
    end

    class << self
      def chrootdir_path
        xdg_cache = File.expand_path(ENV.fetch('XDG_CACHE_HOME', '~/.cache'))
        File.expand_path('quack_aur/chroot', xdg_cache)
      end
    end

    private

    def chroot_build_command
      command = ['makechrootpkg', '-c', '-r', @chrootdir]
      command + @built_packages.map do |dependency|
        ['-I', File.expand_path(dependency, @origindir)]
      end.flatten
    end

    def build_dry_run
      @chrootdir = Chroot.chrootdir_path
      unless Dir.exist?(@chrootdir)
        puts "[dry-run] mkarchroot #{@chrootdir}/root base-devel"
      end
      puts "[dry-run] arch-nspawn #{@chrootdir}/root pacman -Syu"
      puts "[dry-run] #{chroot_build_command.join(' ')}"
    end

    def build_chrootdir
      @chrootdir = Chroot.chrootdir_path
      inner_rootdir = File.expand_path('root', @chrootdir)
      return inner_rootdir if Dir.exist?(inner_rootdir)

      FileUtils.mkdir_p @chrootdir
      # Create chroot dir
      system('mkarchroot', inner_rootdir, 'base-devel', exception: true)
      inner_rootdir
    end

    def build_current
      inner_rootdir = build_chrootdir
      # Make sure chroot is up to date
      system('arch-nspawn', inner_rootdir, 'pacman', '-Syu', exception: true)
      # Actually build the package
      system(*chroot_build_command, exception: true)
    end
  end
end
