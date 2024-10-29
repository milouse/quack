# frozen_string_literal: true

require 'yaml'
require_relative 'trsl/locale'

Psych.add_domain_type('net.umaneti.quack,2024', 'declinable') do |_, data|
  Trsl::Declinable.new data
end

# Trsl (Translate), is a simple localization helper.
module Trsl
  @locale_files_path = nil
  @current_locale = nil
  @locales_cache = {}
  @cache_semaphore = Thread::Mutex.new

  # Set the locale and return it.
  #
  # This method must be called at least once at the beginning of your program.
  # By default, if a locale_code is not given, it defaults on the current LANG
  # environment variable.
  #
  # It can also be used to change the current loaded locale.
  #
  # Warning: this method is not thread-safe and changing the locale of your
  # application more than once could lead to unwanted behavior. For specific
  # temporary locale change, you should consider calling ::change_locale
  # instead.
  #
  # Exemple:
  #     # ENV['LANG'] = 'en'
  #     Trsl.init => #<Trsl::Locale:0x0000…>
  #     Trsl['hello'] # => 'Hello!'
  #     Trsl.init('fr') # => #<Trsl::Locale:0x0000…>
  #     Trsl['hello'] # => 'Salut !'
  def self.init(locale_code = nil, **kwargs)
    @locale_files_path = kwargs.fetch(
      :locale_files_path, File.join(Dir.pwd, 'locales')
    )
    default_locale = kwargs.fetch(:default_locale, 'en')
    locale_code ||= ENV.fetch('LANG', default_locale)
    @current_locale = locale locale_code
  end

  # Reset configuration, as if init was never called.
  # Maybe only useful for test purpose?
  def self.reset!
    @cache_semaphore.synchronize do
      @locale_files_path = nil
      Thread.current[:current_locale] = @current_locale = nil
      @locales_cache = {}
    end
  end

  def self.current_locale
    @current_locale
  end

  # Will autoload a locale from the user environment if one is not already
  # loaded.
  def self.[](term, opts = {})
    (Thread.current[:current_locale] || @current_locale).translate(term, opts)
  rescue NoMethodError
    warn 'No current locale set. Please call Trsl::init first.'
    term
  end

  # Will autoload a locale from the user environment if one is not already
  # loaded.
  #
  # DEPRECATED: will be removed in favor of something else.
  #
  # This method smells of :reek:UncommunicativeMethodName on purpose to keep
  # a short API
  def self.l(object, format = nil)
    @current_locale.localize(object, format)
  rescue NoMethodError
    warn 'No current locale set. Please call Trsl::init first.'
    term
  end

  def self.flatten_hash(hash, keyprefix = '')
    hash.flat_map do |key, value|
      next [["#{keyprefix}#{key}", value]] unless value.is_a? Hash

      flatten_hash(value, "#{keyprefix}#{key}.")
    end
  end

  # Return given locale, after having loaded it in the cache if needed
  def self.locale(locale_code)
    unless @locales_cache.has_key?(locale_code)
      @cache_semaphore.synchronize { load_locale locale_code }
    end
    @locales_cache[locale_code]
  end

  # Change temporarily the locale inside the given block.
  #
  # Return the block return value. If no block is given, do nothing.
  #
  # Exemple:
  #     # ENV['LANG'] = 'fr'
  #     Trsl['hello'] # => 'Salut !'
  #     Trsl.change_locale('en') { |l| l.t('hello') } # => 'Hello!'
  #     Trsl['hello'] # => 'Salut !'
  def self.change_locale(locale_code)
    return unless block_given?

    cur_thread = Thread.current
    old_locale = cur_thread[:current_locale]
    cur_thread[:current_locale] = locale locale_code
    output = yield self
    cur_thread[:current_locale] = old_locale
    output
  end

  def self.possible_lang_codes(locale_code)
    # Poor-man extracter of something like en_US.UTF-8
    locale_no_charset = locale_code.split('.').first
    short_locale = locale_no_charset.split('_').first
    [short_locale, locale_no_charset, locale_code].uniq
  end

  def self.find_locale_file(possible_codes)
    possible_file_paths = possible_codes.filter_map do |lang|
      path = File.join(@locale_files_path, "#{lang}.yml")
      next unless File.exist? path

      path
    end
    raise 'No translations file found' if possible_file_paths.empty?

    possible_file_paths.first
  end

  def self.load_locale(locale_code)
    possible_codes = possible_lang_codes(locale_code)
    i18n_file = find_locale_file possible_codes
    locale = Locale.new i18n_file
    possible_codes.each do |lang|
      @locales_cache[lang] = locale
    end
  end
end
