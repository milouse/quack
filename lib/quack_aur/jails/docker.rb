# frozen_string_literal: true

require_relative '../helper'
require_relative '../jail'

module QuackAur
  # Isolate package building in a docker container
  class Docker < Jail
    def build
      unless QuackAur.which('docker')
        QuackAur.print_error(
          'jail.missing_dependency',
          package: 'docker', jail: 'docker'
        )
        return []
      end
      unless @dry_run
        Dir.mktmpdir('quack_aur_') do |path|
          Dir.chdir(path) { build_docker_image }
        end
      end
      super
    end

    class << self
      def containers_list
        command = QuackAur.sudo_wrapper(
          ['docker', 'container', 'ls', '--all',
           '--filter', 'ancestor=packaging',
           '--filter', 'status=exited', '--quiet']
        )
        QuackAur.capture_no_err command
      end

      def images_list
        command = QuackAur.sudo_wrapper(
          %w[docker image ls packaging --quiet]
        )
        QuackAur.capture_no_err command
      end

      %i[container image].each do |what|
        define_method :"prune_#{what}s" do
          objects = send(:"#{what}s_list")
          number = objects.length
          return number if number.zero?

          system(
            *QuackAur.sudo_wrapper(%W[docker #{what} rm] + objects),
            exception: true
          )
          number
        end
      end
    end

    private

    def build_dry_run
      puts "[dry-run] #{I18n.t('jail.docker_dry_run.build_image')}"
      puts "[dry-run] #{I18n.t('jail.docker_dry_run.roadmap')} >>>>"
      build_docker_roadmap
      puts '<<<<'
      puts "[dry-run] #{I18n.t('jail.docker_dry_run.run')}"
    end

    def build_current
      build_docker_roadmap

      system(
        *QuackAur.sudo_wrapper(
          ['docker', 'run', '--rm', '--name', 'packaging',
           '--ulimit', 'nofile=1024', '--mount',
           "type=bind,source=#{@tmpdir},destination=/home/package/pkg",
           'packaging']
        )
      )
    end

    def build_docker_image
      dockerfile = <<~DOCKER
        FROM archlinux:base-devel

        RUN useradd -m -d /home/package -c 'Package Creation User' -s /usr/bin/bash -g users package && \\
            mkdir -p /run/user/1000 && chown package:users /run/user/1000 && \\
            echo 'package ALL=(ALL) NOPASSWD: /usr/bin/pacman' >> /etc/sudoers && \\
            sed -i 's/^#IgnorePkg *= *$/IgnorePkg = pacman-mirrorlist/' /etc/pacman.conf

        COPY mirrorlist /etc/pacman.d/mirrorlist

        RUN pacman -Syy && pacman -S --noconfirm archlinux-keyring && \\
            pacman -S --noconfirm devtools

        # Little hack to be able to force update of base image
        ARG CACHE_DATE="-"
        RUN pacman -Syu --noconfirm && pacman -Scc

        # Do it only now in case the file is overwritten by a previous update
        RUN sed -i 's/^OPTIONS=(strip docs !libtool !staticlibs emptydirs zipman purge debug lto)$/OPTIONS=(strip docs !libtool !staticlibs !emptydirs zipman purge !debug lto)/' /etc/makepkg.conf

        USER package
        WORKDIR /home/package/pkg

        ENTRYPOINT ["./roadmap.sh"]
      DOCKER
      File.write('Dockerfile', dockerfile)
      FileUtils.cp('/etc/pacman.d/mirrorlist', 'mirrorlist')
      today = Time.now.strftime('%Y-%m-%d')
      system(
        *QuackAur.sudo_wrapper(
          ['docker', 'build', '-t', 'packaging',
           '--build-arg', "CACHE_DATE=#{today}", '.']
        )
      )
    end

    def end_user_dependencies_lines
      # Allow one to provides is own operations before building the
      # package. It may by usefull to install other invisible dependencies.
      my_roadmap_file = File.expand_path 'my.roadmap.sh', @tmpdir
      return [] unless File.exist?(my_roadmap_file)

      File.readlines(my_roadmap_file).map(&:chomp)
    end

    def build_dependencies_lines
      @built_packages.filter_map do |dependency|
        local_file = File.expand_path dependency, @origindir
        FileUtils.cp local_file, @tmpdir
        install_line = "sudo pacman -U --asdeps --noconfirm #{dependency}"
        next if roadmap.include?(install_line)

        install_line
      end
    end

    def build_docker_roadmap
      roadmap = ['#!/usr/bin/env sh', 'set -e',
                 'sudo pacman -Syu --noconfirm'] \
                + end_user_dependencies_lines \
                + build_dependencies_lines
      roadmap << 'exec makepkg -s --noconfirm --skipinteg'
      if @dry_run
        puts roadmap
        return
      end
      File.write 'roadmap.sh', roadmap.join("\n")
      File.chmod 0o755, 'roadmap.sh'
    end
  end
end
