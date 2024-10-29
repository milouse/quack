# frozen_string_literal: true

# Monkey patch to add some helpers
module TimePatch
  refine Time do
    # Localized version of strftime, by translating months and days
    def strftime_locale(format)
      time_format_spec = Trsl['locale.time']
      return strftime(format) unless time_format_spec

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
      strftime(format)
    end
  end
end
