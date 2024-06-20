# frozen_string_literal: true

require 'json'
require 'open3'
require 'net/http'
require_relative 'helper'

module QuackAur
  # A Package hold information related to individual AUR package.
  #
  # This class alone cannot be used to actually install or upgrade
  # a package. Only to retrieve its information from AUR or the local system.
  class Package
    def initialize(package_data)
      @data = package_data
      expand
    end

    def name
      @data['Name']
    end

    def version
      @data['Version']
    end

    def description
      @data['Description']
    end

    def [](key)
      @data[key]
    end

    def []=(key, value)
      @data[key] = value
    end

    def ==(other)
      return false unless other.is_a?(Package)

      equal?(other) || @data['Name'] == other.name
    end

    def outdated?
      @data['OutOfDate'] != nil
    end

    def local?
      return true if @data['LocalVersion']

      version_rx = /\AVersion +: (?<version>[a-z0-9_.-]+)\z/
      QuackAur.capture_no_err(
        %W[pacman -Qi #{@data['Name']}]
      ).each do |line|
        check = version_rx.match(line)
        next unless check

        @data['LocalVersion'] = check[:version]
        return true
      end
      false
    end

    def upgrade?
      return false unless local?
      return true if Package.devel?(@data['Name'])
      return false if @data['LocalVersion'] == @data['Version']

      check = QuackAur.capture_no_err(
        ['vercmp', @data['LocalVersion'], @data['Version']]
      ).first.to_i
      return true if check == -1

      if check == 1
        QuackAur.print_warning('build.newer_version', package: @data['Name'])
      end
      false
    end

    # We only care about AUR dependencies as the others will not be a problem to
    # retrieve and install
    def extract_dependencies(dependencies_chain = [])
      %w[MakeDepends Depends].each do |deps_type|
        next unless @data[deps_type]&.any?

        @data[deps_type].each do |package_name|
          # Remove fixed versionning
          real_name = package_name.split(/[<>=]+/, 2).first.strip
          # Is it an officially supported package?
          next if QuackAur.system?('pacman', '-Si', real_name)

          package = Package.details(real_name)
          # It may happen for some virtual packages or group, which will
          # normally be resolved by pacman itself
          next unless package

          # It has already be processed, for exemple as a dependency of one of
          # its previous dependencies. Do not process it twice.
          next if dependencies_chain.include?(package)

          if package['PackageBase'] == @data['PackageBase']
            # The dependency will be build in the same main package build
            # process. Thus no need to treat it specially.
            unless dependencies_chain.include?(self)
              # Add it only to the chain if self is not already in there (as
              # previous test was only against package Name instead of
              # BaseName).
              dependencies_chain << package
            end
            next
          end

          # Now we must look deeper for dependencies BEFORE adding self to the
          # dependencies chain in order to keep a working installation order.
          dependencies_chain = package.extract_dependencies(dependencies_chain)

          # Finally adding new AUR dependency to the chain.
          dependencies_chain << package
        end
      end
      dependencies_chain
    end

    class << self
      def devel?(package_name)
        package_name.end_with?(*%w[-bzr -cvs -git -hg -svn])
      end

      def local?(package_name)
        QuackAur.system?('pacman', '-Qi', package_name)
      end

      def details(package_name)
        # remove possible aur/ prefix
        search_term = package_name.delete_prefix('aur/')
        search([search_term], method: :info).first
      end

      def search(terms, method: :search)
        request_uri = [
          'https://aur.archlinux.org/rpc/v5', method,
          terms.join('%20') # search only protection
        ].join('/')
        content = JSON.parse(Net::HTTP.get(URI(request_uri)))
        return [] unless content.has_key?('results')

        content['results'].map do |package|
          new(package)
        end
      end
    end

    private

    def expand
      if @data['Maintainer']
        @data['Maintainer'] = format(
          '%<nick>s  https://aur.archlinux.org/account/%<nick>s',
          nick: @data['Maintainer']
        )
      end
      if @data['LastModified']
        @data['LastModified'] = Time.at(@data['LastModified'])
      end
      @data['OutOfDate'] = Time.at(@data['OutOfDate']) if @data['OutOfDate']
      @data['AurPage'] = "https://aur.archlinux.org/packages/#{@data['Name']}"
      @data['CARCH'] = `uname -m`.chomp
      package_tarball = format(
        '/var/cache/pacman/pkg/%<base>s-%<version>s-%<arch>s.pkg.tar.zst',
        base: @data['PackageBase'], version: @data['Version'],
        arch: @data['CARCH']
      )
      @data['TargetCachePath'] = package_tarball
      @data['BuiltPackages'] = []
      if File.exist?(package_tarball) && !Package.devel?(@data['Name'])
        @data['BuiltPackages'] << package_tarball
      end
    end
  end
end
