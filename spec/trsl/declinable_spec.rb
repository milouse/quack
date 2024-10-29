# frozen_string_literal: true

require_relative '../../lib/trsl'

RSpec.describe Trsl::Declinable do
  before { Trsl.init }

  it 'combines plural by default' do
    data = { 0 => 'none', 1 => 'one', 'other' => 'many' }
    dec = described_class.new data
    expect(dec.combines(number: 0)).to eq 'none'
  end

  it 'combines on a given variable name' do
    data = {
      '_variable' => 'fruit',
      'apple' => 'pomme',
      'banana' => 'banane'
    }
    dec = described_class.new data
    expect(dec.combines(fruit: 'banana')).to eq 'banane'
  end

  it 'fallbacks on other key', :aggregate_failures do
    data = { 0 => 'none', 1 => 'one', 'other' => 'many' }
    expect(described_class.new(data).combines(number: 42)).to eq 'many'

    data = { '_variable' => 'fruit', 'other' => 'yummy' }
    expect(described_class.new(data).combines(fruit: 'kiwi')).to eq 'yummy'
  end

  it 'fails if no fallback is found' do
    data = { 0 => 'none', 1 => 'one' }
    dec = described_class.new data
    expect { dec.combines(number: 42) }.to \
      raise_error(RuntimeError, /^No fallback found/)
  end
end
