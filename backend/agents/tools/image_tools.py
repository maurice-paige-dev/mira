import os
import uuid

from langchain_core.tools import tool

from backend.config import S3_IMAGES_BUCKET, CDN_BASE_URL, AWS_REGION
from backend.telemetry import get_logger

log = get_logger("image_tools")


def _get_s3_client():
    import boto3
    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=AWS_REGION,
    )
    return session.client("s3")


def _cdn_key(product_name: str, variant: str) -> str:
    safe = product_name.lower().replace(" ", "-")
    return f"products/{safe}/{variant}.jpg"


@tool
def get_image_url(product_name: str, variant: str = "full") -> str:
    """Get the CDN URL for a product image by variant (thumbnail, full)."""
    key = _cdn_key(product_name, variant)
    url = f"{CDN_BASE_URL}/{key}"
    return url


@tool
def upload_image_tool(product_name: str, variant: str = "full", base64_data: str = "") -> str:
    """Upload a product image (base64-encoded) to the CDN and return its URL."""
    import base64
    import tempfile

    if not base64_data:
        return "No image data provided."

    try:
        image_bytes = base64.b64decode(base64_data)
    except Exception as e:
        return f"Invalid base64 data: {e}"

    key = _cdn_key(product_name, variant)
    try:
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=S3_IMAGES_BUCKET,
            Key=key,
            Body=image_bytes,
            ContentType="image/jpeg",
        )
        url = f"{CDN_BASE_URL}/{key}"
        log.info("image_uploaded", product=product_name, variant=variant, size=len(image_bytes))
        return f"Image uploaded successfully.\nProduct: {product_name}\nVariant: {variant}\nCDN URL: {url}\nSize: {len(image_bytes)} bytes"
    except Exception as e:
        log.error("image_upload_failed", product=product_name, error=str(e))
        return f"Failed to upload image: {e}"


@tool
def list_product_images(product_name: str) -> str:
    """List all available images for a product."""
    prefix = _cdn_key(product_name, "").rsplit("/", 1)[0] + "/"
    try:
        s3 = _get_s3_client()
        response = s3.list_objects_v2(Bucket=S3_IMAGES_BUCKET, Prefix=prefix)
        if "Contents" not in response:
            return f"No images found for '{product_name}'."
        lines = [f"Images for {product_name}:"]
        for obj in response["Contents"]:
            key = obj["Key"]
            variant = key.rsplit("/", 1)[-1].replace(".jpg", "")
            url = f"{CDN_BASE_URL}/{key}"
            lines.append(f"- {variant}: {url}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list images: {e}"


@tool
def delete_image(product_name: str, variant: str) -> str:
    """Delete a product image from the CDN."""
    key = _cdn_key(product_name, variant)
    try:
        s3 = _get_s3_client()
        s3.delete_object(Bucket=S3_IMAGES_BUCKET, Key=key)
        log.info("image_deleted", product=product_name, variant=variant)
        return f"Image deleted: {product_name}/{variant}"
    except Exception as e:
        return f"Failed to delete image: {e}"
