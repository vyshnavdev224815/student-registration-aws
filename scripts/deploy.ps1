param(
    [string]$KeyName = 'roomsplit-vyshnavdev-key',
    [string]$SshCidr
)

$ErrorActionPreference = 'Stop'
$region = 'ap-south-1'
$stackName = 'vyshnav-student-registration'
$expectedAccount = '511999299525'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Push-Location $repoRoot
try {
    $account = (aws sts get-caller-identity --query Account --output text --region $region).Trim()
    if ($LASTEXITCODE -ne 0 -or $account -ne $expectedAccount) {
        throw "AWS CLI must be signed in to account $expectedAccount before deployment."
    }

    if (-not $SshCidr) {
        $publicIp = (Invoke-RestMethod -Uri 'https://checkip.amazonaws.com').Trim()
        $SshCidr = "$publicIp/32"
    }
    if ($SshCidr -notmatch '^(\d{1,3}\.){3}\d{1,3}/32$') {
        throw 'SshCidr must be one public IPv4 address ending in /32.'
    }

    aws cloudformation validate-template --template-body file://infrastructure/student-app.yaml --region $region | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'CloudFormation template validation failed.' }

    aws cloudformation deploy --stack-name $stackName --template-file infrastructure/student-app.yaml `
        --parameter-overrides "Prefix=vyshnav" "SshCidr=$SshCidr" "KeyName=$KeyName" `
        --capabilities CAPABILITY_NAMED_IAM --region $region
    if ($LASTEXITCODE -ne 0) { throw 'CloudFormation deployment failed. Inspect stack events before retrying.' }

    $outputs = aws cloudformation describe-stacks --stack-name $stackName --region $region `
        --query 'Stacks[0].Outputs' --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Could not read stack outputs.' }
    $result = @{}
    foreach ($entry in $outputs) { $result[$entry.OutputKey] = $entry.OutputValue }

    $package = Join-Path $repoRoot 'deployment-package.tar.gz'
    tar -czf $package app.py bootstrap_db.py requirements.txt templates static scripts/install-on-ec2.sh scripts/flaskapp.service scripts/student-app.nginx.conf
    if ($LASTEXITCODE -ne 0) { throw 'Could not package the application.' }
    aws s3 cp $package "s3://$($result.PhotoBucketName)/deployment/deployment-package.tar.gz" --region $region
    if ($LASTEXITCODE -ne 0) { throw 'Could not upload the deployment package.' }

    $online = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $ping = aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$($result.WebInstanceId)" `
            --region $region --query 'InstanceInformationList[0].PingStatus' --output text
        if ($ping -eq 'Online') { $online = $true; break }
        Start-Sleep -Seconds 10
    }
    if (-not $online) { throw 'EC2 did not appear online in Systems Manager within five minutes.' }

    $commands = @(
        "aws s3 cp s3://$($result.PhotoBucketName)/deployment/deployment-package.tar.gz /tmp/student-app.tar.gz --region $region",
        'mkdir -p /tmp/student-app-deploy && tar -xzf /tmp/student-app.tar.gz -C /tmp/student-app-deploy',
        "cd /tmp/student-app-deploy && DB_HOST='$($result.DatabaseEndpoint)' DB_SECRET_ARN='$($result.DatabaseSecretArn)' S3_BUCKET_NAME='$($result.PhotoBucketName)' bash scripts/install-on-ec2.sh"
    )
    $parameterJson = @{ commands = $commands } | ConvertTo-Json -Compress -Depth 4
    $commandId = (aws ssm send-command --instance-ids $result.WebInstanceId `
        --document-name AWS-RunShellScript --comment 'Install student registration app' `
        --parameters $parameterJson --region $region --query 'Command.CommandId' --output text).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $commandId) { throw 'Could not send the install command to EC2.' }

    Write-Output "SSM command: $commandId"
    Write-Output "Application URL: $($result.ApplicationUrl)"
    Write-Output "To check installation: aws ssm get-command-invocation --command-id $commandId --instance-id $($result.WebInstanceId) --region $region"
}
finally {
    Pop-Location
}
