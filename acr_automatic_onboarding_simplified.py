__author__ = "Simon Melotte"

import os
import json
import requests
import argparse
import logging
from dotenv import load_dotenv

# Create a logger object
logger = logging.getLogger()


def add_container_registries(
    base_url,
    token,
    existing_container_registries,
    acr_list,
    credential_id,
    collection_name,
    cap,
    scanners
):
    """
    Updates container registries in Prisma Cloud Compute. Checks if a registry
    with the same name exists:
      - If it does not exist, it is created with the specified parameters.
      - If it does exist and has different parameters, it is removed and re-added.
      - If it does exist and matches all parameters, no changes.
    """
    url = f"{base_url}/api/v1/settings/registry?project=Central+Console&scanLater=false"
    headers = {
        "content-type": "application/json; charset=UTF-8",
        "Authorization": "Bearer " + token,
    }

    existing_specifications = existing_container_registries.get("specifications", [])

    for registry in acr_list.get("resources", []):
        # Construct the registry name from ACR resource
        registry_name = f"{registry['name'].lower()}.azurecr.io"

        # Check if the registry already exists
        matching_indices = [
            i
            for i, existing_registry in enumerate(existing_specifications)
            if existing_registry.get("registry") == registry_name
        ]

        if matching_indices:
            # We only look at the first match since name uniqueness is assumed
            idx = matching_indices[0]
            existing_reg = existing_specifications[idx]

            # Check if parameters match: credentialID, collections, cap, scanners
            same_credential = (existing_reg.get("credentialID") == credential_id)
            same_collections = (existing_reg.get("collections") == [collection_name])
            same_cap = (existing_reg.get("cap") == cap)
            same_scanners = (existing_reg.get("scanners") == scanners)

            if all([same_credential, same_collections, same_cap, same_scanners]):
                logger.info(
                    f"Registry '{registry_name}' already exists and matches parameters. No update needed."
                )
                continue
            else:
                # Remove the old registry if parameters differ
                existing_specifications.pop(idx)
                logger.info(
                    f"Registry '{registry_name}' exists but parameters differ. Removing and re-adding."
                )

        # Create new registry entry with the new parameters
        new_registry = {
            "version": "azure",
            "registry": registry_name,
            "namespace": "",
            "repository": "*",
            "tag": "",
            "credentialID": credential_id,
            "os": "linux",
            "harborDeploymentSecurity": False,
            "collections": [collection_name],
            "cap": cap,
            "scanners": scanners,
            "versionPattern": "",
            "gitlabRegistrySpec": {},
        }

        # Add the new registry to the specifications list
        existing_specifications.append(new_registry)
        logger.info(f"Registry '{registry_name}' has been added or updated.")

    # Update the container registries in Prisma Cloud Compute
    payload = json.dumps(existing_container_registries)
    try:
        response = requests.put(url, headers=headers, data=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as err:
        logger.error("An exception occurred in add_container_registries:", err)
        if response is not None:
            logger.error(f"{response.text}")
        return None

    logger.info("Container registries have been updated successfully.")
    return existing_container_registries


def onboard_workflow(
    compute_url,
    compute_token,
    acr_list_from_cspm,
    acr_list_from_cwp,
    credential_id,
    collection_name,
    cap,
    scanners,
    clean=False
):
    """
    High-level workflow to demonstrate how to integrate the add_container_registries function.
    If clean=True, remove all Azure Container Registries first, then add new ones.
    """
    # 1) If --clean is passed, remove all Azure container registries
    if clean:
        logger.info("Cleaning all Azure container registries (version == 'azure').")
        original_count = len(acr_list_from_cwp.get("specifications", []))
        acr_list_from_cwp["specifications"] = [
            reg
            for reg in acr_list_from_cwp.get("specifications", [])
            if reg.get("version") != "azure"
        ]
        cleaned_count = len(acr_list_from_cwp["specifications"])
        logger.info(f"Removed {original_count - cleaned_count} Azure registries.")

        # Update the registry list on Prisma Cloud Compute with the removal
        registry_url = f"{compute_url}/api/v1/settings/registry?project=Central+Console&scanLater=false"
        headers = {
            "content-type": "application/json; charset=UTF-8",
            "Authorization": "Bearer " + compute_token,
        }
        try:
            response = requests.put(registry_url, headers=headers, data=json.dumps(acr_list_from_cwp))
            response.raise_for_status()
            logger.info("Successfully removed all Azure container registries.")
        except requests.exceptions.RequestException as err:
            logger.error("An exception occurred during the clean step:", err)
            return

    # 2) Add new Azure Container Registries from CSPM data
    add_container_registries(
        base_url=compute_url,
        token=compute_token,
        existing_container_registries=acr_list_from_cwp,
        acr_list=acr_list_from_cspm,
        credential_id=credential_id,
        collection_name=collection_name,
        cap=cap,
        scanners=scanners
    )


def get_container_registries(base_url, token):
    url = f"{base_url}/api/v1/settings/registry?project=Central+Console"
    headers = {"content-type": "application/json; charset=UTF-8", "Authorization": "Bearer " + token}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in get_container_registries,", err)
        if response is not None:
            logger.error(f"{response.text}")
        return None

    logger.debug(f"Response status code: {response.status_code}")
    logger.debug(f"Response headers: {response.headers}")
    logger.debug(f"Response text: {response.text}")
    return response.json()


def get_images_number_per_regristry(base_url, token):
    """
    Creates a summary of how many images are scanned per registry.
    """
    url = f"{base_url}/api/v1/registry?compact=true?project=Central+Console"
    headers = {"content-type": "application/json; charset=UTF-8", "Authorization": "Bearer " + token}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in get_container_registries,", err)
        if response is not None:
            logger.error(f"{response.text}")
        return None

    response_json = response.json()
    registry_count = {}

    for item in response_json:
        for tag in item["tags"]:
            registry = tag["registry"]
            registry_count[registry] = registry_count.get(registry, 0) + 1

    # Sort the dictionary in descending order by value
    sorted_registry_count = dict(sorted(registry_count.items(), key=lambda item: item[1], reverse=True))
    return sorted_registry_count


def get_acr(base_url, token):
    """
    Retrieves Azure Container Registries from Prisma Cloud (CSPM side).
    """
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
        response.raise_for_status()
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in get_acr,", err)
        return None

    return response.json()


def read_authorized_subscriptions():
    """
    Example function to filter authorized subscriptions, if needed.
    """
    file_path = "authorized_sub.conf"
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r") as f:
        subscriptions = [line.strip() for line in f]
    return subscriptions


def read_unauthorized_subscriptions():
    """
    Example function to filter unauthorized subscriptions, if needed.
    """
    file_path = "unauthorized_sub.conf"
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r") as f:
        subscriptions = [line.strip() for line in f]
    return subscriptions


def get_compute_url(base_url, token):
    url = f"https://{base_url}/meta_info"
    headers = {"content-type": "application/json; charset=UTF-8", "Authorization": "Bearer " + token}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as err:
        logger.error("Oops! An exception occurred in get_compute_url,", err)
        return None

    response_json = response.json()
    return response_json.get("twistlockUrl", None)


def login_saas(base_url, access_key, secret_key):
    url = f"https://{base_url}/login"
    payload = json.dumps({"username": access_key, "password": secret_key})
    headers = {"content-type": "application/json; charset=UTF-8"}
    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
    except Exception as e:
        logger.info(f"Error in login_saas: {e}")
        return None

    return response.json().get("token")


def login_compute(base_url, access_key, secret_key):
    """
    Login to the Prisma Cloud Compute (Twistlock) API.
    """
    logger.info(f"Compute base URL: {base_url}")
    url = f"{base_url}/api/v1/authenticate"

    payload = json.dumps({"username": access_key, "password": secret_key})
    headers = {"content-type": "application/json; charset=UTF-8"}

    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as err:
        logger.error("Error logging into Compute API:", err)
        return None

    return response.json().get("token")


def main():
    # Configure the logger
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filename='app.log',
        filemode='a'
    )

    # Create a console handler
    console_handler = logging.StreamHandler()
    # Add the console handler to the logger
    logger.addHandler(console_handler)

    logger.info(f"======================= START =======================")
    logger.debug(f"======================= terminal =======================")

    parser = argparse.ArgumentParser()

    # Existing actions
    parser.add_argument(
        "--report", action="store_true",
        help="Provides a summary of registries with the number of images in descending order."
    )
    parser.add_argument("--onboard", action="store_true", help="Onboard ACR container registries from CSPM.")

    # New parameters
    parser.add_argument(
        "--clean",
        action="store_true",
        help="If specified, removes all Azure container registries from Prisma Cloud Compute."
    )
    parser.add_argument(
        "--credential-id", 
        type=str, 
        default="default-credential",
        help="Name of the credential to use for new Azure Container Registries."
    )
    parser.add_argument(
        "--collection-name", 
        type=str, 
        default="All",
        help="Collection name to associate with new Azure Container Registries."
    )
    parser.add_argument(
        "--cap", 
        type=int, 
        default=2,
        help="CAP value to assign to new Azure Container Registries."
    )
    parser.add_argument(
        "--scanners", 
        type=int, 
        default=6,
        help="Number of scanners to assign to new Azure Container Registries."
    )

    args = parser.parse_args()

    load_dotenv()
    url = os.environ.get("PRISMA_API_URL")
    identity = os.environ.get("PRISMA_ACCESS_KEY")
    secret = os.environ.get("PRISMA_SECRET_KEY")

    if not url or not identity or not secret:
        logger.error(
            "PRISMA_API_URL, PRISMA_ACCESS_KEY, PRISMA_SECRET_KEY environment variables are required."
        )
        return

    # Login to Prisma Cloud SaaS
    token = login_saas(url, identity, secret)
    if token is None:
        logger.error("Unable to authenticate to Prisma SaaS.")
        return

    # Retrieve Prisma Cloud Compute URL and token
    compute_url = get_compute_url(url, token)
    if not compute_url:
        logger.error("Could not retrieve Compute URL from Prisma SaaS.")
        return

    compute_token = login_compute(compute_url, identity, secret)
    if not compute_token:
        logger.error("Unable to authenticate to Prisma Compute.")
        return

    logger.debug(f"Compute url: {compute_url}")

    # Report mode: show how many images exist per registry
    if args.report:
        logger.info("Running in report mode")
        registry_count = get_images_number_per_regristry(compute_url, compute_token)
        if registry_count is None:
            logger.error("Could not retrieve registry images count.")
        else:
            for registry, count in registry_count.items():
                logger.info(f"Registry: {registry}, Number of Images: {count}")

    # Onboard mode: simply add all discovered ACRs
    elif args.onboard:
        logger.info("Running in onboard mode")
        acr_list_from_cspm = get_acr(url, token)
        if acr_list_from_cspm is None:
            logger.error("Could not retrieve ACR list from CSPM.")
            return

        acr_list_from_cwp = get_container_registries(compute_url, compute_token)
        if acr_list_from_cwp is None:
            logger.error("Could not retrieve existing registries from Compute.")
            return

        onboard_workflow(
            compute_url=compute_url,
            compute_token=compute_token,
            acr_list_from_cspm=acr_list_from_cspm,
            acr_list_from_cwp=acr_list_from_cwp,
            credential_id=args.credential_id,
            collection_name=args.collection_name,
            cap=args.cap,
            scanners=args.scanners,
            clean=args.clean
        )

    else:
        logger.error("No valid mode arguments provided. Use --report / --update / --onboard.")

    logger.info(f"======================= END =======================")


if __name__ == "__main__":
    main()
