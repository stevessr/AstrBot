"""
Matrix Web Client 媒体文件处理模块
"""

import aiohttp
from quart import Response, request

from astrbot.api import logger


async def handle_media_download(server_name: str, media_id: str):
    """代理下载媒体文件，修复跨域问题"""
    try:
        # 构建 Matrix 媒体 URL
        media_url = (
            f"https://{server_name}/_matrix/media/r0/download/{server_name}/{media_id}"
        )

        # 获取查询参数
        args = request.args
        if args:
            query_string = "&".join([f"{k}={v}" for k, v in args.items()])
            media_url += f"?{query_string}"

        # 代理请求
        async with aiohttp.ClientSession() as session:
            async with session.get(media_url) as resp:
                if resp.status == 200:
                    # 获取内容类型
                    content_type = resp.headers.get(
                        "content-type", "application/octet-stream"
                    )

                    # 获取内容长度
                    content_length = resp.headers.get("content-length")

                    # 创建响应
                    response = await resp.read()

                    # 设置响应头
                    headers = {
                        "Content-Type": content_type,
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type",
                    }

                    if content_length:
                        headers["Content-Length"] = content_length

                    # 添加缓存控制
                    headers["Cache-Control"] = "public, max-age=86400"  # 缓存一天

                    return Response(response, headers=headers)
                else:
                    logger.error(f"Failed to download media: HTTP {resp.status}")
                    return Response("Media not found", status=404)

    except Exception as e:
        logger.error(f"Error downloading media: {e}")
        return Response("Error downloading media", status=500)


async def handle_media_thumbnail(server_name: str, media_id: str):
    """代理获取媒体文件缩略图"""
    try:
        # 获取查询参数
        args = request.args
        width = args.get("width", "256")
        height = args.get("height", "256")
        method = args.get("method", "scale")

        # 构建 Matrix 缩略图 URL
        thumbnail_url = (
            f"https://{server_name}/_matrix/media/r0/thumbnail/{server_name}/{media_id}"
        )

        # 添加查询参数
        params = f"?width={width}&height={height}&method={method}"
        if args:
            for k, v in args.items():
                if k not in ["width", "height", "method"]:
                    params += f"&{k}={v}"

        thumbnail_url += params

        # 代理请求
        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail_url) as resp:
                if resp.status == 200:
                    # 获取内容类型
                    content_type = resp.headers.get("content-type", "image/jpeg")

                    # 获取内容长度
                    content_length = resp.headers.get("content-length")

                    # 创建响应
                    response = await resp.read()

                    # 设置响应头
                    headers = {
                        "Content-Type": content_type,
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type",
                    }

                    if content_length:
                        headers["Content-Length"] = content_length

                    # 添加缓存控制
                    headers["Cache-Control"] = "public, max-age=86400"  # 缓存一天

                    return Response(response, headers=headers)
                else:
                    logger.error(f"Failed to get thumbnail: HTTP {resp.status}")
                    return Response("Thumbnail not found", status=404)

    except Exception as e:
        logger.error(f"Error getting thumbnail: {e}")
        return Response("Error getting thumbnail", status=500)


async def handle_file_upload(client_manager):
    """处理文件上传到 Matrix 媒体服务器"""
    from quart import jsonify

    session_id = (await request.form).get("session_id")

    if not session_id or session_id not in client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    # 获取上传的文件
    files = await request.files
    if "file" not in files:
        return jsonify({"success": False, "error": "No file provided"})

    file = files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected"})

    try:
        client_data = client_manager.matrix_clients[session_id]
        client = client_data["client"]

        # 读取文件内容
        file_content = file.read()
        logger.debug(
            f"File content type: {type(file_content)}, size: {len(file_content)}"
        )

        # 获取 MIME 类型
        content_type = file.content_type or "application/octet-stream"

        # 上传到 Matrix 媒体服务器
        try:
            upload_response = await client.upload_file(
                data=file_content, content_type=content_type, filename=file.filename
            )
        except Exception as upload_error:
            logger.error(f"Upload error: {upload_error}")
            raise

        # 返回内容 URI
        content_uri = upload_response.get("content_uri")
        if content_uri:
            return jsonify({"success": True, "content_uri": content_uri})
        else:
            return jsonify(
                {"success": False, "error": "Upload failed: no content_uri returned"}
            )

    except Exception as e:
        logger.error(f"Failed to upload file: {e}")
        return jsonify({"success": False, "error": str(e)})
