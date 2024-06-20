# frozen_string_literal: true

require_relative 'lib/quack_aur/version'

Gem::Specification.new do |spec|
  spec.name        = 'quack_aur'
  spec.version     = QuackAur::VERSION
  spec.summary     = 'A Qualitative and Usable pACKage helper for AUR'
  spec.authors     = ['Étienne Deparis']
  spec.email       = 'etienne@depar.is'
  spec.metadata    = {
    'rubygems_mfa_required' => 'true',
    'source_code_uri' => 'https://git.umaneti.net/quack',
    'funding_uri' => 'https://liberapay.com/milouse'
  }
  spec.files = [
    'lib/l10n.rb',
    'lib/quack_aur/aur.rb',
    'lib/quack_aur/cleaner.rb',
    'lib/quack_aur/helper.rb',
    'lib/quack_aur/jail.rb',
    'lib/quack_aur/jails/chroot.rb',
    'lib/quack_aur/jails/docker.rb',
    'lib/quack_aur/package.rb',
    'lib/quack_aur/version.rb',
    # Translations
    'locales/en.yml',
    'locales/fr.yml',
    # Others
    'CONTRIBUTING.org',
    'README.org',
    'LICENSE'
  ]
  spec.executables = ['quackaur']
  spec.homepage    = 'https://git.umaneti.net/quack/about/'
  spec.license     = 'WTFPL'

  spec.required_ruby_version = '>= 3.0'
  spec.add_runtime_dependency 'rainbow', '~> 3.1'

  spec.requirements << 'git'
  spec.requirements << 'pacman'
end
