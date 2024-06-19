# frozen_string_literal: true

require 'open3'
require 'English'
require_relative 'jails/docker'
require_relative 'helper'

module Quack
  class Cleaner
    def initialize(options)
      @color = Quack.setup_color_mode options[:color]
      @deep_search = options[:deep_search]
    end

    def list
      Quack.print_log 'cleaner.orphaned_packages'
      if !system(*%W[pacman --color #{@color} -Qdt]) \
         && $CHILD_STATUS.exitstatus == 1
        Quack.print_result 'cleaner.no_orphaned_packages'
      end
      Quack.print_log 'cleaner.transac_files', new_line: true
      if @deep_search
        result = transac_files_from_deep_search
      else
        result = transac_files_from_pacman_db
      end
      if result == ''
        Quack.print_result 'cleaner.no_transac_files'
      else
        puts result
      end
      cached_packages
      docker_garbage
    end

    def purge
      if Quack.which('paccache')
        Quack.print_log 'cleaner.removing_packages'
        system('paccache', '-r')
      else
        Quack.print_warning 'cleaner.no_paccache'
      end
      purge_docker
    end

    private

    def transac_files_from_deep_search
      command = ['find', '/boot/', '/etc/', '/usr/', '-type', 'f', '(']
      %w[*.pacsave *.pacorig *.pacnew].each do |file|
        command += %W[-name #{file} -o]
      end
      command.pop # remove last -o
      command << ')'
      Quack.capture_no_err Quack.sudo_wrapper(command)
    end

    def transac_files_from_pacman_db
      results = []
      suffixes = %w[pacsave pacorig pacnew]
      Dir['/var/lib/pacman/local/*/files'].each do |file|
        has_backup = false
        File.readlines(file).each do |line|
          if line == "%BACKUP%\n"
            has_backup = true
            next
          elsif has_backup
            backup_prefix = "/#{line.split("\t").first}"
            suffixes.each do |file_ext|
              test_file = "#{backup_prefix}.#{file_ext}"
              results << test_file if File.exist?(test_file)
            end
          end
        end
      end
      results.join("\n")
    end

    def cached_packages
      return unless Quack.which('paccache')

      Quack.print_log 'cleaner.removed_packages', new_line: true
      command = %w[paccache -du]
      command << '--nocolor' if @color == :never
      # I cannot redirect stderr as for a weird reason it removes the
      # color
      output, = Open3.capture2(*command)
      puts output.strip

      Quack.print_log 'cleaner.old_packages', new_line: true
      command[1] = '-d'
      # Same here
      output, = Open3.capture2(*command)
      puts output.strip
    end

    def docker_garbage
      return unless Quack.which('docker')

      %w[containers images].each do |what|
        Quack.print_log "cleaner.docker.#{what}", new_line: true
        number = Docker.send(:"#{what}_list").length
        Quack.print_result(
          "cleaner.docker.#{what}_found", number: number
        )
      end
    end

    def purge_docker
      return unless Quack.which('docker')

      %w[containers images].each do |what|
        Quack.print_log(
          "cleaner.docker.removing_#{what}", new_line: true
        )
        number = Docker.send(:"prune_#{what}")
        Quack.print_result(
          "cleaner.docker.removed_#{what}", number: number
        )
      end
    end
  end
end
