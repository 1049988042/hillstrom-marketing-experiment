$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'src/create_split.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python (Join-Path $PSScriptRoot 'src/heterogeneity.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m unittest discover -s (Join-Path $PSScriptRoot 'tests') -v
exit $LASTEXITCODE
