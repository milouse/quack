# frozen_string_literal: true

require_relative 'lib/quack/version'

Gem::Specification.new do |spec|
  spec.name        = 'quack'
  spec.version     = Quack::VERSION
  spec.summary     = 'A Qualitative and Usable Aur paCKage helper'
  spec.authors     = ['Étienne Deparis']
  spec.email       = 'etienne@depar.is'
  spec.metadata    = {
    'rubygems_mfa_required' => 'true',
    'source_code_uri' => 'https://git.umaneti.net/quack',
    'funding_uri' => 'https://liberapay.com/milouse'
  }
  spec.files = [
    'lib/l10n.rb',
    'lib/quack/aur.rb',
    'lib/quack/cleaner.rb',
    'lib/quack/helper.rb',
    'lib/quack/jail.rb',
    'lib/quack/jails/chroot.rb',
    'lib/quack/jails/docker.rb',
    'lib/quack/package.rb',
    'lib/quack/version.rb',
    # Translations
    'locales/en.yml',
    'locales/fr.yml',
    # Others
    'CONTRIBUTING.org',
    'README.org',
    'LICENSE'
  ]
  spec.executables = ['quack']
  spec.homepage    = 'https://git.umaneti.net/quack/about/'
  spec.license     = 'WTFPL'

  spec.required_ruby_version = '>= 3.0'
  spec.add_runtime_dependency 'rainbow', '~> 3.1'

  spec.requirements << 'git'
  spec.requirements << 'pacman'
end
