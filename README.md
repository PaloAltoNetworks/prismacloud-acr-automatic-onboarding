# Purpose of the Script

This Python script is designed to streamline and automate the process of onboarding Azure Container Registries (ACR) into Prisma Cloud. Given the complexity and potential volume of Azure subscriptions and container registries within those subscriptions, manually managing them can become a significant challenge. This script offers a solution by automatically onboard all ACR into Compute by listing  into Prisma Cloud and subsequently onboarding the respective container registries. 

## Account Onboarding Information
In this script, you have the ability to selectively onboard container registries across various Azure subscriptions into Prisma Cloud by specifying the Azure subscriptions ID in the `authorized_sub.conf` configuration file.

However, it's important to note the following behavior:

**Onboarding All Registries Across All Subscriptions**

If you leave the `authorized_sub.conf` file empty, the script will onboard all registries across all Azure subscriptions that have been onboarded into Prisma Cloud.

**Preventing Specific Prisma Cloud Accounts from Onboarding**

You can prevent specific Prisma Cloud accounts from being onboarded using the `unauthorized_sub.conf` file. This file allows you to list the Prisma Cloud Account Names (not the Azure subscription names) that you do not want to be onboarded.

## Pre requesites from Azure

### Create a SP on Azure

Use the az ad sp create-for-rbac command to create a Service Principal:
```bash
az account set --subscription "<your-subscription-id>"
az ad sp create-for-rbac --name "<your-app-name>"
```

This will return a JSON object that contains your service principal's appId and password.  

To assign the same Service Principal to multiple subscriptions, you would have to create role assignments for each subscriptions.  
So, for each of your subscriptions, run a command like this:
```bash
az role assignment create --assignee <app-id> --role AcrPull --scope /subscriptions/<subscription-id>
```

### Automate the SP Creation and the Role Assignment

You can use the bash script in this repository with the following command

```bash
./create_service_principal.sh "<myAppName>" "<tenant_id>"
```

## Set your environment variables

Copy .env.example to .env file and edit the following informations

```bash
PRISMA_API_URL="__REDACTED__"
PRISMA_ACCESS_KEY="__REDACTED__"
PRISMA_SECRET_KEY="__REDACTED__"
AZURE_CLIENT_ID="__REDACTED__"
AZURE_CLIENT_SECRET="__REDACTED__"
AZURE_TENANT_ID="__REDACTED__"
```

[OPTIONAL] Or you can export the information into environment variables

```bash
export PRISMA_API_URL="__REDACTED__"
export PRISMA_ACCESS_KEY="__REDACTED__"
export PRISMA_SECRET_KEY="__REDACTED__"
export AZURE_CLIENT_ID="__REDACTED__"
export AZURE_CLIENT_SECRET="__REDACTED__"
export AZURE_TENANT_ID="__REDACTED__"
```

## Run the Python script

```bash
python3 -m virtualenv venv && source venv/bin/activate
pip install -r requirements.txt
python3 acr_automatic_onboarding.py --help
## Onboard ACR container registries from CSPM
python3 acr_automatic_onboarding.py --onboard
## Provides a summary of registries with the number of images in descending order
python3 acr_automatic_onboarding.py --report
## Onboard only ACR whihc are not yet onboarded
python3 acr_automatic_onboarding.py --update
```