# frozen_string_literal: true

require_relative '../helper'
require_relative '../jail'

module QuackAur
  class Docker < Jail
    def build
      unless QuackAur.which('docker')
        QuackAur.print_error(
          'jail.missing_dependency',
          package: 'docker', jail: 'docker'
        )
        return []
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
      puts "[dry-run] #{Trsl['jail.docker_dry_run.build_image']}"
      puts "[dry-run] #{Trsl['jail.docker_dry_run.roadmap']} >>>>"
      build_docker_roadmap
      puts '<<<<'
      puts "[dry-run] #{Trsl['jail.docker_dry_run.run']}"
    end

    def build_current
      return unless build_docker_image

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

        RUN useradd -m -d /home/package -c 'Package Creation User' -s /usr/bin/bash -g users package && \
            mkdir -p /run/user/1000 && chown package:users /run/user/1000 && \
            echo 'package ALL=(ALL) NOPASSWD: /usr/bin/pacman' >> /etc/sudoers && \
            echo 'Server = https://mirrors.gandi.net/archlinux/$repo/os/$arch' > /etc/pacman.d/mirrorlist && \
            pacman -Sy --noconfirm archlinux-keyring && \
            pacman -S --noconfirm devtools

        USER package
        WORKDIR /home/package/pkg

        ARG CACHE_DATE="-"
        RUN sudo pacman -Syyu --noconfirm && sudo pacman -Scc

        ENTRYPOINT ["/usr/bin/sh", "roadmap.sh"]
      DOCKER
      File.write('Dockerfile.quack', dockerfile)
      today = Time.now.strftime('%Y-%m-%d')
      system(
        *QuackAur.sudo_wrapper(
          ['docker', 'build', '-t', 'packaging',
           '--build-arg', "CACHE_DATE=#{today}", '-']
        ), in: 'Dockerfile.quack'
      )
    end

    def build_docker_roadmap
      roadmap = ['#!/usr/bin/env sh', 'set -e', 'sudo pacman -Syyu --noconfirm']
      # Allow one to provides is own operations before building the
      # package. It may by usefull to install other invisible dependencies.
      my_roadmap_file = File.expand_path 'my.roadmap.sh', @tmpdir
      if File.exist?(my_roadmap_file)
        roadmap += File.readlines(my_roadmap_file).map(&:chomp)
      end
      @built_packages.each do |dependency|
        local_file = File.expand_path dependency, @origindir
        FileUtils.cp local_file, @tmpdir
        install_line = "sudo pacman -U --asdeps --noconfirm #{dependency}"
        next if roadmap.include?(install_line)

        roadmap << install_line
      end
      roadmap << 'exec makepkg -s --noconfirm --skipinteg'
      roadmap_content = roadmap.join("\n")
      if @dry_run
        puts roadmap_content
        return
      end
      File.write('roadmap.sh', roadmap_content)
    end
  end
end
