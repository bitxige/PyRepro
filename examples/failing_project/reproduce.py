"""Reproduce the deterministic P0 parser failure."""

from app.parser import parse_lane

parse_lane({"id": "lane-1"})
