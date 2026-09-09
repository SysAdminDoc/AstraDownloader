#!/usr/bin/env python3
"""Handle frozen multiprocessing workers before application imports."""
import multiprocessing
multiprocessing.freeze_support()
