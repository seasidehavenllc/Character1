---
title: Ruby
summary: Expressive, friendly language best known for Ruby on Rails web apps; also great for scripting.
tags: [language, web, backend, rails, scripting]
---
# Ruby

## Overview
Ruby is designed to be pleasant to write. Everything is an object, and blocks make collection code read like English. Ruby on Rails is a productive framework for building database-backed web apps quickly (GitHub and Shopify started on it).

## Setup and running
- Install with a version manager (`rbenv` or `asdf`) or RubyInstaller on Windows. Check: `ruby -v`.
- Run: `ruby main.rb`. Interactive: `irb`.
- Packages are "gems": `gem install name`, or a `Gemfile` with Bundler. Rails: `gem install rails && rails new app`.

## Core syntax
```ruby
name = "Tony"
power = 100
suits = ["Mark I", "Mark II"]
suits << "Mark III"
levels = { "Mark I" => 40, mark2: 55 }      # hash; mark2: is a symbol key

puts "#{name} has #{power}% power" if power > 50
suits.each_with_index { |suit, i| puts "#{i}: #{suit}" }

def square(x) = x * x                       # one-line method
evens = (1..10).select(&:even?)             # blocks and symbols
total = [3, 1, 4].sum
```

## Classes
```ruby
class Robot
  attr_reader :name, :battery

  def initialize(name)
    @name = name                           # @ = instance variable
    @battery = 100
  end

  def move(cm)
    raise ArgumentError, "not enough battery" if cm * 2 > @battery
    @battery -= cm * 2
    self
  end
end
```

## Common mistakes
- Forgetting that only `nil` and `false` are falsy (`0` and `""` are true).
- Mutating strings or arrays shared elsewhere; use `.dup` or frozen strings.
- Confusing symbol keys (`:name`) and string keys (`"name"`) in hashes.
- In Rails: N+1 database queries; use `includes`.

## Learning path
### Level 1 — Basics
Variables, strings, numbers, arrays, hashes, conditionals, loops and blocks, methods.
Exercise: a shopping-list script that totals prices from a hash.

### Level 2 — Objects
Classes, modules, mixins, `Enumerable`, exceptions, file I/O, gems and Bundler.
Exercise: a text adventure with rooms as objects.

### Level 3 — Rails
MVC, routes, controllers, views, ActiveRecord models, migrations, validations, forms.
Exercise: a blog with posts and comments.

### Level 4 — Production
Authentication, background jobs, testing (RSpec, Minitest), APIs, deployment.
Exercise: add user accounts and an API endpoint to the blog and deploy it.

## Complete example
```ruby run
Reading = Struct.new(:sensor, :cm)

readings = [Reading.new("front", 42), Reading.new("left", 17), Reading.new("right", 88)]
closest = readings.min_by(&:cm)
near, far = readings.partition { |r| r.cm < 50 }

puts "Closest: #{closest.sensor} (#{closest.cm} cm)"
puts "Near: #{near.map(&:sensor).join(', ')}; far: #{far.map(&:sensor).join(', ')}"
```
