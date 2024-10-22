__author__ = "Simon Melotte"

import os
import json
import requests
import argparse
import logging
from dotenv import load_dotenv

# Create a logger object
logger = logging.getLogger()


def add_container_registries(base_url, token, existing_container_registries, acr_list, account, force=False):
    accountId, accountName = account  # Unpack account tuple
    url = f"{base_url}/api/v1/settings/registry?project=Central+Console&scanLater=false"
    headers = {
        "content-type": "application/json; charset=UTF-8",
        "Authorization": "Bearer " + token,
    }

    for registry in acr_list["resources"]:
        if registry["accountId"] == accountId:
            registry_name = f"{registry['name'].lower()}.azurecr.io"
            existing_specifications = existing_container_registries["specifications"]

            # Find if the registry already exists
            existing_indices = [
                i
                for i, existing_registry in enumerate(existing_specifications)
                if existing_registry["registry"] == registry_name
            ]

            if existing_indices:
                if force:
                    # Remove the existing registry
                    index_to_remove = existing_indices[0]  # Assuming unique registry names
                    existing_specifications.pop(index_to_remove)
                    logger.info(f"Registry {registry_name} exists and will be replaced due to force=True")
                else:
                    logger.info(f"Registry {registry_name} already exists in Prisma Cloud")
                    continue  # Skip to next registry

            # Create new registry entry
            new_registry = {
                "version": "azure",
                "registry": registry_name,
                "namespace": "",
                "repository": "*",
                "tag": "",
                "credentialID": f"{accountId}-servicekey",
                "os": "linux",
                "harborDeploymentSecurity": False,
                "collections": ["All"],
                "cap": 2,
                "scanners": 6,
                "versionPattern": "",
                "gitlabRegistrySpec": {},
            }

            # Add the new registry to the specifications list
            existing_specifications.append(new_registry)
            logger.info(f"Registry {registry_name} has been added")
        else:
            # Skip if accountId does not match
            continue

    # Convert the updated registries to JSON
    payload = json.dumps(existing_container_registries)

    try:
        response = requests.put(url, headers=headers, data=payload)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx
    except requests.exceptions.RequestException as err:
        logger.error("An exception occurred in add_container_registries:", err)
        logger.error(f"{response.text}")
        return None

    logger.info(f"All registries for subscription {accountName} have been added successfully")


def onboard_workflow(
    url,
    token,
    compute_url,
    compute_token,
    azure_client_id,
    azure_client_secret,
    acr_list_from_cspm,
    acr_list_from_cwp,
    azure_tenant_id,
    force=False
):
    logger.info(f"Number of container registries to onboard: {len(acr_list_from_cspm['resources'])}")

    unique_account_ids = get_unique_account_ids(url, token, acr_list_from_cspm, azure_tenant_id)
    logger.info(f"Number of azure cloud accounts that contains ACR: {len(unique_account_ids)}")

    authorized_subscriptions = read_authorized_subscriptions()
    unauthorized_subscriptions = read_unauthorized_subscriptions()

    # Create a cloud account in the compute part with the service key
    for account in unique_account_ids:
        if not any(sub in account[1] for sub in unauthorized_subscriptions):
            if not authorized_subscriptions or account[0] in authorized_subscriptions:
                create_cloud_account(
                    compute_url, compute_token, account, azure_client_id, azure_client_secret, azure_tenant_id
                )
                set_cloud_scan_rules(compute_url, compute_token, account)
                add_container_registries(compute_url, compute_token, acr_list_from_cwp, acr_list_from_cspm, account, force)
            else:
                logger.info(f"Account {account[0]} is not authorized.")
        else:
            logger.info(f"Account {account[0]} is explicitly denied by the configuration.")


def get_container_registries(base_url, token):
    url = f"{base_url}/api/v1/settings/registry?project=Central+Console"
    headers = {"content-type": "application/json; charset=UTF-8", "Authorization": "Bearer " + token}

    try:
        response = requests.request("GET", url, headers=headers)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in get_container_registries, ", err)
        logger.error(f"{response.text}")
        return None

    logger.debug(f"Response status code: {response.status_code}")
    logger.debug(f"Response headers: {response.headers}")
    logger.debug(f"Response text: {response.text}")
    return response.json()


def get_images_number_per_regristry(base_url, token):
    url = f"{base_url}/api/v1/registry?compact=true?project=Central+Console"
    headers = {"content-type": "application/json; charset=UTF-8", "Authorization": "Bearer " + token}

    try:
        response = requests.request("GET", url, headers=headers)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in get_container_registries, ", err)
        logger.error(f"{response.text}")
        return None

    response_json = response.json()
    registry_count = {}

    for item in response_json:
        for tag in item["tags"]:
            registry = tag["registry"]
            if registry not in registry_count:
                registry_count[registry] = 1
            else:
                registry_count[registry] += 1

    # Sort the dictionary in descending order by value
    sorted_registry_count = dict(sorted(registry_count.items(), key=lambda item: item[1], reverse=True))
    return sorted_registry_count


def set_cloud_scan_rules(base_url, token, account):
    accountId, accountName = account  # Unpack account tuple

    url = f"{base_url}/api/v1/cloud-scan-rules?project=Central+Console"
    headers = {"content-type": "application/json; charset=UTF-8", "Authorization": "Bearer " + token}

    payload = json.dumps(
        [
            {
                "credentialId": f"{accountId}-servicekey",
                "discoveryEnabled": False,
                "agentlessScanSpec": {},
                "serverlessScanSpec": {},
                "awsRegionType": "regular",
            }
        ]
    )

    try:
        response = requests.request("PUT", url, headers=headers, data=payload)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in set_cloud_scan_rules, ", err)
        logger.error(f"{response.text}")
        return None


def create_cloud_account(base_url, token, account, azure_client_id, azure_client_secret, azure_tenant_id):
    accountId, accountName = account  # Unpack account tuple

    url = f"{base_url}/api/v1/credentials?project=Central+Console"
    headers = {"content-type": "application/json; charset=UTF-8", "Authorization": "Bearer " + token}

    secret_json = json.dumps(
        {
            "clientId": azure_client_id,
            "clientSecret": f"{azure_client_secret}",
            "tenantId": f"{azure_tenant_id}",
            "subscriptionId": f"{accountId}",
            "activeDirectoryEndpointUrl": "https://login.microsoftonline.com",
            "resourceManagerEndpointUrl": "https://management.azure.com/",
            "activeDirectoryGraphResourceId": "https://graph.windows.net/",
            "sqlManagementEndpointUrl": "https://management.core.windows.net:8443/",
            "galleryEndpointUrl": "https://gallery.azure.com/",
            "managementEndpointUrl": "https://management.core.windows.net/",
        }
    )

    payload = json.dumps(
        {
            "caCert": "",
            "secret": {"encrypted": "", "plain": secret_json},
            "apiToken": {"encrypted": "", "plain": ""},
            "description": (f"{accountName}-servicekey")[:30],
            "skipVerify": False,
            "accountID": "",
            "useAWSRole": False,
            "_id": f"{accountId}-servicekey",
            "type": "azure",
            "accountName": f"{accountName}-servicekey",
            "useSTSRegionalEndpoint": False,
        }
    )

    try:
        response = requests.request("POST", url, headers=headers, data=payload)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in create_cloud_account, ", err)
        logger.error(f"{response.text}")
        return None

    logger.debug(f"Response status code: {response.status_code}")
    logger.debug(f"Response headers: {response.headers}")
    logger.debug(f"Response text: {response.text}")
    return response


def get_subscriptions_by_tenant(base_url, token, azure_tenant_id):
    url = f"https://{base_url}/search/config"
    headers = {"content-type": "application/json; charset=UTF-8", "x-redlock-auth": token}

    limit = 100
    next_page_token = None
    rql = f"config from cloud.resource where cloud.type = 'azure' AND api.name = 'azure-subscription-list' AND json.rule = tenantId equals \"{azure_tenant_id}\""

    # Initial request to get totalRows
    payload = json.dumps(
        {
            "limit": limit,
            "query": rql,
            "timeRange": {"type": "relative", "value": {"unit": "hour", "amount": 24}, "relativeTimeType": "BACKWARD"},
            "nextPageToken": next_page_token,
        }
    )

    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in get_subscriptions_by_tenant, ", err)
        return None

    json_response = response.json()

    # Initialize items with first page data
    items = json_response["data"]["items"]
    total_rows = json_response["data"]["totalRows"]
    data = json_response.get("data", {})
    next_page_token = data.get("nextPageToken", None)
    while total_rows > 0:
        logger.info(f"Total subscriptions part of the tenant: {len(items)}")
        if not next_page_token:
            break  # Break the loop if no nextPageToken found
        # Update URL to get the next page
        url = f"https://{base_url}/search/config/page"
        payload = json.dumps(
            {
                "limit": limit,
                "pageToken": next_page_token,
            }
        )

        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx

        json_response = response.json()
        # Append the items from the next page to items list
        items.extend(json_response["items"])
        total_rows = json_response["totalRows"]
        next_page_token = json_response.get("nextPageToken", None)

    return {"data": {"items": items}}


def get_unique_account_ids(base_url, token, acr_list, azure_tenant_id):
    tenant_subscriptions = get_subscriptions_by_tenant(base_url, token, azure_tenant_id)

    # Map account IDs to account names. Create empty dict if no subscriptions.
    tenant_account_ids = (
        {item["accountId"]: item["accountName"] for item in tenant_subscriptions["data"]["items"]}
        if tenant_subscriptions
        else {}
    )

    unique_account_ids = set()
    for resource in acr_list["resources"]:
        account_id = resource["accountId"]
        if account_id in tenant_account_ids:
            account_name = tenant_account_ids[account_id]
            unique_account_ids.add((account_id, account_name))

    return list(unique_account_ids)


def get_acr(base_url, token):
    url = f"https://{base_url}/resource/scan_info"
    headers = {"content-type": "application/json; charset=UTF-8", "x-redlock-auth": token}

    payload = json.dumps(
        {
            "filters": [
                {"name": "includeEventForeignEntities", "operator": "=", "value": "false"},
                {"name": "cloud.service", "operator": "=", "value": "Azure Container Registry"},
                {"name": "cloud.type", "operator": "=", "value": "azure"},
                {"name": "resource.type", "operator": "=", "value": "Azure Container Registry"},
                {"name": "scan.status", "operator": "=", "value": "all"},
                {"name": "decorateWithDerivedRRN", "operator": "=", "value": False},
            ],
            "limit": 10000,
            "timeRange": {"type": "to_now", "value": "epoch"},
        }
    )

    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in get_acr, ", err)
        return None

    return response.json()


def read_authorized_subscriptions():
    with open("authorized_sub.conf", "r") as f:
        subscriptions = [line.strip() for line in f]
    return subscriptions


def read_unauthorized_subscriptions():
    with open("unauthorized_sub.conf", "r") as f:
        subscriptions = [line.strip() for line in f]
    return subscriptions


def get_compute_url(base_url, token):
    url = f"https://{base_url}/meta_info"
    headers = {"content-type": "application/json; charset=UTF-8", "Authorization": "Bearer " + token}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in get_compute_url, ", err)
        return None

    response_json = response.json()
    return response_json.get("twistlockUrl", None)


def login_saas(base_url, access_key, secret_key):
    url = f"https://{base_url}/login"
    payload = json.dumps({"username": access_key, "password": secret_key})
    headers = {"content-type": "application/json; charset=UTF-8"}
    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx
    except Exception as e:
        logger.info(f"Error in login_saas: {e}")
        return None

    return response.json().get("token")


def login_compute(base_url, access_key, secret_key):
    url = f"{base_url}/api/v1/authenticate"

    payload = json.dumps({"username": access_key, "password": secret_key})
    headers = {"content-type": "application/json; charset=UTF-8"}
    response = requests.post(url, headers=headers, data=payload)
    return response.json()["token"]


def main():
    # Configure the logger
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        filename='app.log',
                        filemode='a')

    # Create a console handler
    console_handler = logging.StreamHandler()

    # Add the console handler to the logger
    logger.addHandler(console_handler)

    logger.info(f"======================= START =======================")
    logger.debug(f"======================= terminal =======================")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report", action="store_true", help="Provides a summary of registries with the number of images in descending order."
    )
    parser.add_argument("--onboard", action="store_true", help="Onboard ACR container registries from CSPM.")
    parser.add_argument("--force-onboard", action="store_true", help="Force Onboard ACR container registries from CSPM.")
    parser.add_argument("--update", action="store_true", help="Onboard newly added container registries.")
    args = parser.parse_args()

    load_dotenv()
    url = os.environ.get("PRISMA_API_URL_NEW")
    identity = os.environ.get("PRISMA_ACCESS_KEY")
    secret = os.environ.get("PRISMA_SECRET_KEY")
    azure_client_id = os.environ.get("AZURE_CLIENT_ID")
    azure_client_secret = os.environ.get("AZURE_CLIENT_SECRET")
    azure_tenant_id = os.environ.get("AZURE_TENANT_ID")

    if not url or not identity or not secret or not azure_client_id or not azure_client_secret or not azure_tenant_id:
        logger.error(
            "PRISMA_API_URL, PRISMA_ACCESS_KEY, PRISMA_SECRET_KEY, AZURE_CLIENT_ID, PRISMA_SECRET_KEY or AZURE_TENANT_ID environment variables are not set."
        )
        return

    token = login_saas(url, identity, secret)
    compute_url = get_compute_url(url, token)
    compute_token = login_compute(compute_url, identity, secret)
    logger.debug(f"Compute url: {compute_url}")

    if token is None:
        logger.error("Unable to authenticate.")
        return

    if args.report:
        logger.info("Running in report mode")
        registry_count = get_images_number_per_regristry(compute_url, compute_token)

        for registry, count in registry_count.items():
            logger.info(f"Registry: {registry}, Number of Images: {count}")
    if args.update:
        logger.info("Running in update mode")

        acr_list_from_cspm = get_acr(url, token)
        acr_list_from_cwp = get_container_registries(compute_url, compute_token)

        # Extract the registry names and convert them to the appropriate format
        registries_from_cwp = {resource["registry"] for resource in acr_list_from_cwp["specifications"]}

        # Modify acr_list_from_cspm to exclude registries that are already onboarded
        acr_list_from_cspm["resources"] = [
            resource
            for resource in acr_list_from_cspm["resources"]
            if f"{resource['name']}.azurecr.io" not in registries_from_cwp
        ]

        onboard_workflow(
            url,
            token,
            compute_url,
            compute_token,
            azure_client_id,
            azure_client_secret,
            acr_list_from_cspm,
            acr_list_from_cwp,
            azure_tenant_id,
        )

    elif args.onboard:
        logger.info("Running in onboard mode")
        acr_list_from_cspm = get_acr(url, token)
        acr_list_from_cwp = get_container_registries(compute_url, compute_token)

        onboard_workflow(
            url,
            token,
            compute_url,
            compute_token,
            azure_client_id,
            azure_client_secret,
            acr_list_from_cspm,
            acr_list_from_cwp,
            azure_tenant_id,
            args.force_onboard,
        )
    elif args.force_onboard:
        logger.info("Running in FORCE onboard mode")
        acr_list_from_cspm = get_acr(url, token)
        acr_list_from_cwp = get_container_registries(compute_url, compute_token)

        onboard_workflow(
            url,
            token,
            compute_url,
            compute_token,
            azure_client_id,
            azure_client_secret,
            acr_list_from_cspm,
            acr_list_from_cwp,
            azure_tenant_id,
            True,
        )
    else:
        logger.error("No arguments provided.")

    logger.info(f"======================= END =======================")


if __name__ == "__main__":
    main()
