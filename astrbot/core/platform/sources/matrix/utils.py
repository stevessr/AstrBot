"""
Matrix 工具方法组件
"""


class MatrixUtils:
    @staticmethod
    def mxc_to_http(mxc_url: str, homeserver: str) -> str:
        if not mxc_url.startswith("mxc://"):
            return mxc_url
        server_name = mxc_url[6:].split("/")[0]
        media_id = mxc_url[6:].split("/")[1]
        return f"{homeserver}/_matrix/media/v3/download/{server_name}/{media_id}"
