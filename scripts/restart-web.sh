#!/usr/bin/env bash
sudo systemctl restart ships-ahoy-web.service && sudo systemctl status ships-ahoy-web.service --no-pager
