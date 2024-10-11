# frozen_string_literal: true

require 'i18n'

i18n_glob = File.expand_path('../../locales', __dir__)
I18n.load_path = Dir["#{i18n_glob}/*.yml"]
