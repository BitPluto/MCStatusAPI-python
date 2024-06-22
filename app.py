from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from mcstatus import JavaServer, BedrockServer
import base64
import asyncio
import dns.resolver
import re
import sys
import logging

app = FastAPI()

async def resolve_srv_record(domain: str):
    try:
        srv_records = dns.resolver.resolve(f"_minecraft._tcp.{domain}", 'SRV')
        if srv_records:
            record = srv_records[0]
            return str(record.target), record.port
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        pass
    return None, None

async def parse_address(address: str):
    ip_port_regex = r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::(\d+))?$"
    match = re.match(ip_port_regex, address)
    if match:
        return match.group(1), int(match.group(2)) if match.group(2) else None, None, None
    else:
        if ":" in address and address[-1] != ":":
            parts = address.split(":")
            return parts[0], int(parts[1]), None, None
        else:
            SRVtarget, SRVport = await resolve_srv_record(address)
            return address, None, SRVtarget, SRVport

async def motd_to_html(motd):
    formatting_map = {
        "colors": {
            "0": "<span style='color:#000000!important'>",
            "1": "<span style='color:#0000AA!important'>",
            "2": "<span style='color:#00AA00!important'>",
            "3": "<span style='color:#00AAAA!important'>",
            "4": "<span style='color:#AA0000!important'>",
            "5": "<span style='color:#AA00AA!important'>",
            "6": "<span style='color:#FFAA00!important'>",
            "7": "<span style='color:#AAAAAA!important'>",
            "8": "<span style='color:#555555!important'>",
            "9": "<span style='color:#5555FF!important'>",
            "a": "<span style='color:#55FF55!important'>",
            "b": "<span style='color:#55FFFF!important'>",
            "c": "<span style='color:#FF5555!important'>",
            "d": "<span style='color:#FF55FF!important'>",
            "e": "<span style='color:#FFFF55!important'>",
            "f": "<span style='color:#FFFFFF!important'>",
        },
        "styles": {
            "l": "font-weight:bold;",
            "o": "font-style:italic;",
            "n": "text-decoration:underline;",
            "m": "text-decoration:line-through;",
            "k": "class='motd-obfuscated'",
        },
    }

    current_html = ""
    current_color = ""
    current_styles = []

    i = 0
    while i < len(motd):
        if motd[i] == '§':
            code = motd[i + 1].lower()

            if code in formatting_map["colors"]:
                # Close all open style spans
                while current_styles:
                    current_html += current_styles.pop()
                # Close previous color span if color is changing
                if current_color != code:
                    if current_color:
                        current_html += "</span>"
                    current_color = code
                    current_html += formatting_map["colors"][code]
                i += 2  # Move past the § and the color code
                continue
            elif code in formatting_map["styles"]:
                style = formatting_map["styles"][code]
                if code == "k":
                	current_html += f"<span {style}>"
                else:
                    current_html += f"<span style='{style}'>"
                current_styles.append("</span>")
                i += 2  # Move past the § and the style code
                continue
            elif code == "r":
                # Reset all formatting
                while current_styles:
                    current_html += current_styles.pop()
                if current_color:
                    current_html += "</span>"
                    current_color = ""
                i += 2  # Move past the § and the 'r'
                continue

        current_html += motd[i]
        i += 1

    # Close any remaining open spans
    while current_styles:
        current_html += current_styles.pop()
    if current_color:
        current_html += "</span>"

    # Replace new lines with <br>
    current_html = current_html.replace("\n", "<br>")

    return current_html

async def get_java_status(address: str):
    try:
        address, port, SRVtarget, SRVport = await parse_address(address)
        java_server = JavaServer.lookup(f"{address}:{port}" if port else address)
        java_status = await asyncio.to_thread(java_server.status)
        java_icon = None
        if hasattr(java_status, 'icon') and java_status.icon:
            java_icon_base64 = java_status.icon.split(",")[1]
            java_icon = base64.b64encode(base64.b64decode(java_icon_base64)).decode("utf-8")
        player_list = [player.name for player in java_status.players.sample] if java_status.players.sample else []
        motd_clean = re.sub(r"\u00A7.", "", java_status.description)
        motd_html = await motd_to_html(java_status.description)
        if port == None:
            port = 25565
        return {
            "online": True,
            "host": address,
            "port": port,
            "srv": {
                "target": SRVtarget,
                "port": SRVport
            },
            "type": "Java",
            "version": {
                "name_clean": java_status.version.name,
                "protocol": java_status.version.protocol
            },
            "players": {
                "online": java_status.players.online,
                "max": java_status.players.max,
                "list": player_list
            },
            "motd": {
                "raw": java_status.description,
                "clean": motd_clean,
                "html": motd_html
            },
            "icon": f"data:image/png;base64,{java_icon}" if java_icon else None
        }
    except Exception as e:
        print(f"Error retrieving Java server status: {e}")
        return {
            "online": False,
            "host": address,
            "port": port,
            "type": "Java"
        }

async def get_bedrock_status(address: str):
    try:
        address, port, SRVtarget, SRVport = await parse_address(address)
        bedrock_server = BedrockServer.lookup(f"{address}:{port}" if port else address)
        bedrock_status = await asyncio.to_thread(bedrock_server.status)
        player_list = bedrock_status.players
        return {
            "online": True,
            "host": address,
            "port": port,
            "srv": {
                "target": SRVtarget,
                "port": SRVport
            },
            "type": "Bedrock",
            "version": bedrock_status.version.name,
            "players": {
                "online": len(player_list),
                "max": bedrock_status.players_max,
                "list": player_list
            },
            "motd": bedrock_status.motd,
            "icon": None
        }
    except Exception as e:
        print(f"Error retrieving Java server status: {e}")
        return {
            "online": False,
            "host": address,
            "port": port,
            "type": "Bedrock",
        }

@app.get("/")
def centered_ad() -> HTMLResponse:
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <title>MC-Status API | ByteBlitz.de</title>
    <style>
    * {{
        color: whitesmoke;
    	font-family: Roboto, sans-serif;
        font-weight: bold;
    }}
    body {{
    	margin: 0;
        background: #212529;
    }}
    .centered-container {{
        display: flex;
        justify-content: center;
        align-items: center;
        height: 100vh;
    }}
    </style>
    </head>
    <body>
    <div class="centered-container">
        <h1>MC-Status API by <a href='https://byteblitz.de'>ByteBlitz</a></h1>
    </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)

@app.get("/{address}")
async def lookup_java_server(address: str):
    if address != "favicon.ico":
        try:
            java_status = await get_java_status(address)
            return java_status
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            print(f"Error: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")

            
@app.get("/bedrock/{address}")
async def lookup_bedrock_server(address: str):
    if address != "favicon.ico":
        try:
            bedrock_status = await get_bedrock_status(address)
            return bedrock_status
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            print(f"Error: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")

# Disable logging for favicon.ico requests
class FaviconFilter(logging.Filter):
    def filter(self, record):
        return "/favicon.ico" not in record.getMessage()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.access")
logger.addFilter(FaviconFilter())

if __name__ == "__main__":
    import uvicorn
    import sys

    # Retrieve the port from the command-line arguments
    if len(sys.argv) != 2:
        print("Usage: python app.py <port>")
        sys.exit(1)
    
    try:
        port = int(sys.argv[1])
    except ValueError:
        print("Port must be an integer.")
        sys.exit(1)

    uvicorn.run(app, host="0.0.0.0", port=port)
