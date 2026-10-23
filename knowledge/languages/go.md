---
title: Go
summary: Simple, fast compiled language for servers, cloud tools, command-line programs and concurrent systems.
tags: [language, backend, cloud, cli, concurrency]
---
# Go

## Overview
Go (Golang) was designed at Google to be simple to read and fast to compile. It builds single-file executables, has built-in concurrency (goroutines and channels), and powers tools like Docker and Kubernetes. Great for web APIs and command-line tools.

## Setup and running
- Install from go.dev. Check: `go version`.
- New project: `mkdir app && cd app && go mod init example.com/app`.
- Run: `go run .` Build: `go build` (cross-compile with `GOOS=windows GOARCH=amd64 go build`). Format: `go fmt ./...`.

## Core syntax
```go
package main

import "fmt"

func divide(a, b float64) (float64, error) {   // multiple return values
	if b == 0 {
		return 0, fmt.Errorf("divide by zero")
	}
	return a / b, nil
}

func main() {
	name := "Tony"                  // := declares and infers type
	var power int = 100
	suits := []string{"Mark I", "Mark II"}   // slice (growable)
	suits = append(suits, "Mark III")
	levels := map[string]int{"Mark I": 40}

	for i, s := range suits {
		fmt.Println(i, s, levels[s])
	}
	if result, err := divide(10, 4); err == nil {
		fmt.Printf("%s: %d%%, %.2f\n", name, power, result)
	}
}
```

## Structs, methods and interfaces
```go
type Rover struct {
	Name     string
	Position int
}

func (r *Rover) Move(cm int) { r.Position += cm }   // pointer receiver modifies the rover

type Mover interface{ Move(cm int) }                 // satisfied automatically by Rover
```

## Concurrency
```go
results := make(chan int)
for _, id := range []int{1, 2, 3} {
	go func(id int) { results <- id * 10 }(id)   // goroutine: runs concurrently
}
for i := 0; i < 3; i++ {
	fmt.Println(<-results)                        // receive from the channel
}
```

## Common mistakes
- Ignoring returned errors (`x, _ := ...`). Handle every `err`.
- Unused imports or variables are compile errors (on purpose).
- Modifying a struct through a value receiver (changes a copy); use a pointer receiver.
- Goroutines that never finish, or reading a shared map from several goroutines without a mutex.
- `nil` maps: `var m map[string]int` must be `make`d before writing.

## Learning path
### Level 1 — Basics
Packages, variables, types, `if`, `for` (Go's only loop), functions, slices, maps.
Exercise: a word-frequency counter for a text file.

### Level 2 — Types and errors
Structs, methods, pointers, interfaces, error handling, packages and modules.
Exercise: a bank account package with deposit/withdraw that returns errors, plus tests (`go test`).

### Level 3 — Concurrency and the web
Goroutines, channels, `sync.WaitGroup`, `context`, `net/http`, JSON.
Exercise: a REST API for notes with the standard library.

### Level 4 — Production
Databases (`database/sql`), structured logging, configuration, Docker, profiling.
Exercise: a URL-checker CLI that checks 100 sites concurrently and reports response times.

## Complete example
```go run
package main

import (
	"fmt"
	"sort"
	"sync"
)

func main() {
	sensors := map[string]int{"front": 42, "left": 17, "right": 88}
	var mu sync.Mutex
	var wg sync.WaitGroup
	alerts := []string{}

	for name, cm := range sensors {
		wg.Add(1)
		go func(name string, cm int) {
			defer wg.Done()
			if cm < 50 {
				mu.Lock()
				alerts = append(alerts, fmt.Sprintf("%s at %d cm", name, cm))
				mu.Unlock()
			}
		}(name, cm)
	}
	wg.Wait()
	sort.Strings(alerts)
	fmt.Println("Obstacles:", alerts)
}
```
