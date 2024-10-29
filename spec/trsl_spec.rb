# frozen_string_literal: true

require_relative '../lib/trsl'

OLD_ENV = ENV.fetch 'LANG', nil

RSpec.describe Trsl do
  let(:locales_dir) { File.expand_path 'spec_locales', __dir__ }

  before do
    FileUtils.mkdir locales_dir
    File.write "#{locales_dir}/fr.yml", "---\n"
  end

  after do
    described_class.reset!
    FileUtils.rm_r locales_dir
    ENV['LANG'] = OLD_ENV
  end

  it 'flattens a hash' do
    data = {
      app: {
        view: { label: 'test' },
        title: 'hello'
      },
      other: 42
    }
    result = [['app.view.label', 'test'], ['app.title', 'hello'], ['other', 42]]
    expect(described_class.flatten_hash(data)).to eq result
  end

  it 'loads current locale', :aggregate_failures do
    ENV['LANG'] = 'fr'
    expect(described_class.current_locale).to be_nil
    described_class.init locale_files_path: locales_dir
    expect(described_class.current_locale).not_to be_nil
    expect(
      described_class.current_locale.instance_variable_get(:@code)
    ).to eq 'fr'
  end

  it 'fails when no file is found for current locale', :aggregate_failures do
    ENV['LANG'] = 'de'
    expect(described_class.current_locale).to be_nil
    expect { described_class.init locale_files_path: locales_dir }.to \
      raise_error RuntimeError, 'No translations file found'
  end
end
