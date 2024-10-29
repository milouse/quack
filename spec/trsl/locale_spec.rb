# frozen_string_literal: true

require_relative '../../lib/trsl'

RSpec.describe Trsl::Locale do
  let(:locales_dir) { File.expand_path 'spec_locales', __dir__ }

  before do
    FileUtils.mkdir locales_dir
    # rubocop:disable Style/FormatStringToken
    locale_content = <<~YAML
      ---
      app:
        view:
          label: test
        title: hello
        results: !declinable
          0: None found
          1: One found
          other: '%<number>i found'
        version: 'version: %{version}'
      other: 42
    YAML
    # rubocop:enable Style/FormatStringToken
    File.write "#{locales_dir}/fr.yml", locale_content
  end

  after do
    FileUtils.rm_r locales_dir
  end

  it 'loads a lang file when it exists' do
    locale = described_class.new "#{locales_dir}/fr.yml"
    expect(locale.instance_variable_get(:@translations)).not_to be_empty
  end

  it 'fails to load a lang when no translations file is found' do
    expect { described_class.new './locales/missing.yml' }.to \
      raise_error(Errno::ENOENT, /^No such file or directory/)
  end

  describe 'with fr locale set' do
    let(:locale_fr) { described_class.new "#{locales_dir}/fr.yml" }

    it 'fails with a missing term' do
      expect { locale_fr.translate('missing.term') }.to \
        raise_error(Trsl::MissingError, 'Term not found')
    end

    it 'translates simple things' do
      expect(locale_fr.translate('other')).to eq '42'
    end

    it 'translates longer chain' do
      expect(locale_fr.translate('app.view.label')).to eq 'test'
    end

    it 'translates terms with variables' do
      expect(
        locale_fr.translate('app.version', version: 'test')
      ).to eq 'version: test'
    end

    it 'fails with missing or unknown variable', :aggregate_failures do
      expect do
        locale_fr.translate('app.version')
      end.to raise_error KeyError, 'key{version} not found'

      expect do
        locale_fr.translate('app.version', test: 'crash')
      end.to raise_error KeyError, 'key{version} not found'
    end

    it 'supports plural form', :aggregate_failures do
      expect(locale_fr.translate('app.results', number: 0)).to eq 'None found'
      expect(locale_fr.translate('app.results', number: 1)).to eq 'One found'
      expect(locale_fr.translate('app.results', number: 42)).to eq '42 found'
    end

    it 'fails with plural form and a bad number' do
      expect do
        locale_fr.translate('app.results', number: 'crash')
      end.to(
        raise_error(
          ArgumentError, 'invalid value for Integer(): "crash"'
        )
      )
    end

    it 'fails with plural form without number', :aggregate_failures do
      expect do
        locale_fr.translate('app.results')
      end.to raise_error KeyError, 'key<number> not found'

      expect do
        locale_fr.translate('app.results', test: 'crash')
      end.to raise_error KeyError, 'key<number> not found'
    end
  end
end
