# frozen_string_literal: true

module Trsl
  # Store declinable strings (plural forms, genders relative…)
  class Declinable
    def initialize(data)
      # Default on plural form
      @variable_name = (data.delete('_variable') || 'number').to_sym
      @data = data
    end

    def to_s
      @data.to_s
    end

    def combines(variables)
      key_check = %w[other]
      if variables.has_key?(@variable_name)
        key_check.unshift variables[@variable_name]
      end
      key_check.each do |key|
        return @data[key] if @data.has_key?(key)
      end

      raise "No fallback found for declinable #{self}"
    end

    def dig(variables)
      begin
        localized_term = combines(variables)
      rescue RuntimeError => error
        raise MissingError.new(error, term)
      end
      while localized_term.is_a? Declinable
        localized_term = localized_term.combines(variables)
      end
      localized_term
    end
  end
end
