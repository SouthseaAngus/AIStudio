#!/bin/zsh
# Compiles the photoscan command next to this script.
set -e
cd "$(dirname "$0")"
swiftc -O -parse-as-library -swift-version 5 photoscan.swift -o photoscan
echo "Built $(pwd)/photoscan"
