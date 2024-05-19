# frozen_string_literal: true

require 'yaml'

# A simple localization helper
module L10n
  @current_locale = nil

  def self.plural_form(localized_term, opts)
    return localized_term unless localized_term.is_a?(Hash)

    value = opts[:number]
    return localized_term unless value

    value = 'other' unless localized_term.has_key?(value)
    localized_term[value]
  end

  # Will autoload a locale from the user environment if one is not already
  # loaded.
  def self.t(term, opts = {})
    @current_locale ||= Locale.new
    @current_locale.translate(term, opts)
  end

  # Will autoload a locale from the user environment if one is not already
  # loaded.
  def self.l(object, format = nil)
    @current_locale ||= Locale.new
    @current_locale.localize(object, format)
  end

  # Change the current loaded locale.
  #
  # When a block is given, change only temporarily the given locale.
  #
  # Exemple:
  #     # ENV['LANG'] = 'en'
  #     L10n.t('hello') # => 'Hello!'
  #     L10n.load('fr') # => nil
  #     L10n.t('hello') # => 'Salut !'
  #     L10n.load('en') { |l| l.t('hello') } # => 'Hello!'
  #     L10n.t('hello') # => 'Salut !'
  def self.load(code, &block)
    old_current = @current_locale
    @current_locale = Locale.new(code)
    return unless block

    output = yield self
    @current_locale = old_current
    output
  end

  # Store all translations and specificities for a given language.
  class Locale
    def initialize(code = ENV.fetch('LANG', 'en'))
      @locale = code
      @locale_file = nil
      find_locale_file
      @translations = YAML.safe_load_file(
        @locale_file, fallback: {}, freeze: true
      )
    end

    def translate(term, opts = {})
      return term if term == ''

      localized_term = @translations.dig(*term.split('.'))
      return term unless localized_term
      return localized_term if opts.empty?

      localized_term = L10n.plural_form(localized_term, opts)

      begin
        format(localized_term, opts)
      rescue TypeError
        localized_term
      end
    end

    def localize(object, format)
      # For now we support only Time object
      case object
      when Time, DateTime
        format_time(object, format || 'locale.time.long')
      when Date
        format_time(object, format || 'locale.date.long')
      else
        object.to_s
      end
    end

    private

    def find_locale_file
      # Poor-man extracter of something like en_US.UTF-8
      locale_no_charset = @locale.split('.').first
      short_locale = locale_no_charset.split('_').first
      [short_locale, locale_no_charset, @locale, 'en'].uniq.each do |lang|
        i18n_file = File.expand_path("../locales/#{lang}.yml", __dir__)
        next unless File.exist?(i18n_file)

        @locale = lang
        @locale_file = i18n_file
        return
      end
      raise 'No translations file found'
    end

    def format_time(time, format)
      format = translate(format).dup

      time_format_spec = @translations.dig('locale', 'time')
      return time.strftime(format) unless time_format_spec

      month_idx = time.month - 1
      day_idx = time.wday
      {
        '%B' => time_format_spec.dig('months', month_idx),
        '%b' => time_format_spec.dig('short_months', month_idx),
        '%A' => time_format_spec.dig('days', day_idx),
        '%a' => time_format_spec.dig('short_days', day_idx)
      }.each do |code, value|
        next unless value

        format.gsub!(code, value)
      end
      time.strftime(format)
    end
  end
end
