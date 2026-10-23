---
title: Lua
summary: Tiny, fast scripting language embedded in games and apps — Roblox (Luau), LÖVE 2D, game mods, Neovim.
tags: [language, games, roblox, scripting, embedded]
---
# Lua

## Overview
Lua is small and easy to embed, so many games and tools use it for scripting: Roblox uses Luau (a typed Lua dialect), LÖVE makes 2D games in Lua, and many game mods and Neovim plugins are Lua. It has one data structure, the table, used for arrays, maps and objects.

## Setup and running
- Install Lua 5.4 (`sudo apt install lua5.4`, `brew install lua`) and run `lua main.lua`.
- Roblox: install Roblox Studio; scripts go in `ServerScriptService` or `StarterPlayerScripts`.
- LÖVE: install from love2d.org; a folder with `main.lua` runs with `love .`.

## Core syntax
```lua
local name = "Tony"                -- always use local
local power = 100
local suits = {"Mark I", "Mark II"} -- table as a list; indexes start at 1!
table.insert(suits, "Mark III")
local levels = { ["Mark I"] = 40, color = "red" }   -- table as a map

if power > 50 and name ~= "" then  -- ~= means "not equal"
  print(name .. " has " .. power .. "% power")       -- .. joins strings
end

for i, suit in ipairs(suits) do print(i, suit) end   -- lists
for key, value in pairs(levels) do print(key, value) end  -- maps

local function square(x) return x * x end
print(#suits)                      -- length
```

## Objects with tables
```lua
local Robot = {}
Robot.__index = Robot

function Robot.new(name)
  return setmetatable({ name = name, battery = 100 }, Robot)
end

function Robot:move(cm)            -- colon passes self
  self.battery = self.battery - cm * 2
end
```

## Roblox (Luau) example
```lua
local part = script.Parent
part.Touched:Connect(function(hit)
  local humanoid = hit.Parent:FindFirstChildOfClass("Humanoid")
  if humanoid then humanoid.Health = 0 end   -- a "lava" brick
end)
```

## Common mistakes
- Forgetting `local`, creating global variables by accident.
- Starting list indexes at 0; Lua starts at 1.
- Using `#` on tables with gaps (`nil` holes) gives unreliable lengths.
- Calling methods with `.` instead of `:` so `self` is missing.
- In Roblox, trusting the client: do important game logic on the server.

## Learning path
### Level 1 — Basics
Variables, strings, numbers, `if`, loops, functions, tables as lists and maps.
Exercise: a text quiz that keeps score.

### Level 2 — Tables and objects
Metatables, OOP with tables, modules (`require`), string library, error handling (`pcall`).
Exercise: an inventory module with add/remove/list.

### Level 3 — Pick a platform
Roblox Studio (parts, events, RemoteEvents, DataStores) or LÖVE (`love.load/update/draw`, input, collisions).
Exercise: a Roblox obby with checkpoints, or a LÖVE Pong clone.

### Level 4 — Ship a game
Game loops, state machines, saving data, UI, multiplayer on Roblox, performance.
Exercise: publish a small Roblox experience or a LÖVE game build.

## Complete example
```lua run
local Robot = {}
Robot.__index = Robot

function Robot.new(name)
  return setmetatable({ name = name, battery = 100, log = {} }, Robot)
end

function Robot:move(cm)
  if cm * 2 > self.battery then return false end
  self.battery = self.battery - cm * 2
  table.insert(self.log, "moved " .. cm .. " cm")
  return true
end

local bot = Robot.new("Dummy")
bot:move(20)
bot:move(45)
print(bot.name .. " battery: " .. bot.battery .. "%")
print(table.concat(bot.log, ", "))
```
