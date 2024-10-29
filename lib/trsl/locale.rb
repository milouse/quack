# frozen_string_literal: true

require_relative 'declinable'
require_relative '../ext/time'
using TimePatch

module Trsl
  # Custom error to be used when a translation is missing
  class MissingError < ::StandardError
    attr_reader :term

    def initialize(message, term)
      @term = term
      super(message)
    end
  end

  # Store all translations and specificities for a given language.
  class Locale
    def initialize(locale_file)
      @locale_file = locale_file
      @code = File.basename @locale_file, '.yml'
      @translations = {}
      load_translations
    end

    def translate(term, opts = {})
      localized_term = @translations[term]
      raise MissingError.new('Term not found', term) unless localized_term

      if localized_term.is_a? Declinable
        localized_term = manage_declinable localized_term, opts
      end

      format(localized_term.to_s, opts)
    end

    # This method smells of :reek:FeatureEnvy as its whole purpose is to route
    # the given object the its right localization method
    def localize(object, format)
      # Avoid a frozen string error
      format = translate(format).dup
      # For now we support only Time object
      case object
      when Time, DateTime
        object.strftime_locale(format || 'locale.time.long')
      when Date
        object.strftime_locale(format || 'locale.date.long')
      else
        object.to_s
      end
    end

    private

    def load_translations
      data = YAML.safe_load_file(
        @locale_file, fallback: {}, freeze: true
      ) || {}
      @translations = Trsl.flatten_hash(data).to_h.freeze
    end

    def manage_declinable(localized_term, opts)
      # Trsl::Declinable have a custom dig implementation
      # rubocop:disable Style/SingleArgumentDig
      localized_term.dig(opts)
      # rubocop:enable Style/SingleArgumentDig
    rescue RuntimeError => error
      raise MissingError.new(error, term)
    end
  end
end
