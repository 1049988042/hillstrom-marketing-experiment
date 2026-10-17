$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'src/policy_evaluation.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m unittest discover -s (Join-Path $PSScriptRoot 'tests') -v
exit $LASTEXITCODE
