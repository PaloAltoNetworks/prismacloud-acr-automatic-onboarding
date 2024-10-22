#!/bin/bash

# Variables
APP_NAME=$1
TENANT_ID=$2

# Check if the Service Principal already exists
SP_EXISTING=$(az ad sp list --display-name $APP_NAME --query "[].appId" --output tsv)

if [ -z "$SP_EXISTING" ] 
then
    SP_EXISTING=$(az ad sp create-for-rbac --name $APP_NAME --query "{ client_id: appId, client_secret: password }" --output tsv)
fi

# Parse the output to get the Service Principal's details
APP_ID=$(echo $SP_EXISTING | awk '{print $1}')
APP_PASSWORD=$(echo $SP_EXISTING | awk '{print $2}')

echo "Service Principal ID: $APP_ID"
echo "Service Principal Password: $APP_PASSWORD"
echo "Tenant ID: $TENANT_ID"

# Get all subscription IDs for the specific tenant
SUBSCRIPTION_IDS=$(az account list --query "[?tenantId=='$TENANT_ID'].id" --output tsv)

# Assign AcrPull role to each subscription
for SUBSCRIPTION_ID in $SUBSCRIPTION_IDS
do    
    # Set the active subscription
    az account set --subscription $SUBSCRIPTION_ID
    
    ROLE_ASSIGNMENT_EXISTING=$(az role assignment list --assignee $APP_ID --role AcrPull --scope /subscriptions/$SUBSCRIPTION_ID --query "[].id" --output tsv)
    if [ -z "$ROLE_ASSIGNMENT_EXISTING" ]
    then
        echo "Assigning AcrPull roles to subscription: $SUBSCRIPTION_ID"
        az role assignment create --assignee $APP_ID --role AcrPull --scope /subscriptions/$SUBSCRIPTION_ID
    else
        echo "Role assignment already exists for Service Principal $APP_ID with role AcrPull on subscription $SUBSCRIPTION_ID"
    fi
done

echo "Finished assigning roles to Service Principal for each subscription."