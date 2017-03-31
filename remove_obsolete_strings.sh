#!/usr/bin/bash
find . -name "*.po" -exec msgattrib {} -o {} --no-obsolete \;
