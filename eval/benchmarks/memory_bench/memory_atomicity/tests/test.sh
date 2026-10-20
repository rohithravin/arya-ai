#!/bin/bash
set -eu
mkdir -p /logs/verifier

uvx --from 'harbor-rewardkit==0.2.*' rewardkit /tests --workspace /workdir
