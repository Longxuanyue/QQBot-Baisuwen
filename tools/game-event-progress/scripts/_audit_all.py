#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容旧入口 → audit.py"""

from audit import main

if __name__ == "__main__":
    raise SystemExit(main())
