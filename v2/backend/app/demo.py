from pathlib import Path

from fastapi.responses import FileResponse


def register_demo_routes(app):
    def demo():
        return FileResponse(Path(__file__).parent / 'static' / 'demo.html', media_type='text/html')

    app.add_api_route('/', demo, methods=['GET'], include_in_schema=False)
    app.add_api_route('/demo', demo, methods=['GET'], include_in_schema=False)
    def agent():
        return FileResponse(Path(__file__).parent/'static'/'agent.html',media_type='text/html')
    app.add_api_route('/agent',agent,methods=['GET'],include_in_schema=False)
