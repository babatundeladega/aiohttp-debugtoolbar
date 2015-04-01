import asyncio
import aiohttp_mako
from aiohttp import web

from .toolbar import DebugToolbar
from .utils import addr_in, REDIRECT_CODES, APP_KEY, TEMPLATE_KEY, hexlify
# from .utils import ToolbarStorage, ExceptionHistory


html_types = ('text/html', 'application/xhtml+xml')


@asyncio.coroutine
def toolbar_middleware_factory(app, handler):
    # just create namespace for handler
    settings = app[APP_KEY]['settings']
    request_history = app[APP_KEY]['request_history']
    exc_history = app[APP_KEY]['exc_history']

    if not app[APP_KEY]['settings']['enabled']:
        return handler


    @asyncio.coroutine
    def toolbar_middleware(request):

        request['exc_history'] = exc_history
        panel_classes = settings.get('panels', {})
        global_panel_classes = settings.get('global_panels', {})
        hosts = settings.get('hosts', [])

        show_on_exc_only = settings.get('show_on_exc_only')
        intercept_redirects = settings['intercept_redirects']

        root_url = request.app.router['debugtoolbar.main'].url()
        exclude_prefixes = settings.get('exclude_prefixes')
        exclude = [root_url] + exclude_prefixes

        p = request.path
        starts_with_excluded = list(filter(None, map(p.startswith, exclude)))

        remote_host, remote_port = request.transport.get_extra_info('peername')

        last_proxy_addr = remote_host

        # TODO: rethink access policy by host
        if starts_with_excluded or not addr_in(last_proxy_addr, hosts):
            return (yield from handler(request))

        toolbar = DebugToolbar(request, panel_classes, global_panel_classes)
        _handler = handler

        # XXX
        for panel in toolbar.panels:
            _handler = panel.wrap_handler(_handler)


        try:
            response = yield from _handler(request)
            toolbar.status = response.status
        except (web.HTTPSuccessful, web.HTTPRedirection) as e:
            # TODO: fix dirty hack
            response = e

        except Exception as e:
            import ipdb; ipdb.set_trace()

            if exc_history is not None:
                # tb = get_traceback(info=sys.exc_info(),
                #                    skip=1,
                #                    show_hidden_frames=False,
                #                    ignore_system_exceptions=True)
                # for frame in tb.frames:
                #     exc_history.frames[frame.id] = frame
                # exc_history.tracebacks[tb.id] = tb
                # request['pdbt_tb'] = tb
                #
                # token = request.app[APP_KEY]['pdtb_token']
                # qs = {'token': token, 'tb': str(tb.id)}
                # msg = 'Exception at %s\ntraceback url: %s'

                # exc_url = debug_toolbar_url(request, 'exception', _query=qs)
                # exc_url = request.app.router['debugtoolbar.exception'].url(qs)
                # exc_msg = msg % (request.url, exc_url)
                # logger.exception(exc_msg)

                # subenviron = request.environ.copy()
                # del subenviron['PATH_INFO']
                # del subenviron['QUERY_STRING']
                # subrequest = type(request).blank(exc_url, subenviron)
                # subrequest.script_name = request.script_name
                # subrequest.path_info = \
                #     subrequest.path_info[len(request.script_name):]
                #
                # response = request.invoke_subrequest(subrequest)
                response = web.Response(body=b'')
                toolbar.process_response(request, response)

                request['id'] = str((id(request)))
                toolbar.status = response.status

                request_history.put(request['id'], toolbar)
                toolbar.inject(request, response)
                return response
            # else:
            #     logger.exception('Exception at %s' % request.path)
                raise e


        if intercept_redirects:
            # Intercept http redirect codes and display an html page with a
            # link to the target.
            if response.status in REDIRECT_CODES and response.location:

                context = {'redirect_to': response.location,
                           'redirect_code': response.status}

                _response = aiohttp_mako.render_template(
                    'redirect.dbtmako', request, context,
                    app_key=TEMPLATE_KEY)
                response = _response

        toolbar.process_response(request, response)
        request['id'] = hexlify(id(request))

        # Don't store the favicon.ico request
        # it's requested by the browser automatically
        if not "/favicon.ico" == request.path:
            request_history.put(request['id'], toolbar)

        if not show_on_exc_only and response.content_type in html_types:
            toolbar.inject(request, response)

        return response

    return toolbar_middleware

toolbar_html_template = """\
<script type="text/javascript">
    var fileref=document.createElement("link")
    fileref.setAttribute("rel", "stylesheet")
    fileref.setAttribute("type", "text/css")
    fileref.setAttribute("href", "%(css_path)s")
    document.getElementsByTagName("head")[0].appendChild(fileref)
</script>

<div id="pDebug">
    <div style="display: block; %(button_style)s" id="pDebugToolbarHandle">
        <a title="Show Toolbar" id="pShowToolBarButton"
           href="%(toolbar_url)s" target="pDebugToolbar">&#171;
        FIXME: Debug Toolbar</a>
    </div>
</div>
"""