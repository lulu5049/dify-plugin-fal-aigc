from dify_plugin import Plugin, DifyPluginEnv

# Dify or a reverse proxy can still enforce a shorter outer timeout.
plugin = Plugin(DifyPluginEnv(MAX_REQUEST_TIMEOUT=900))

if __name__ == '__main__':
    plugin.run()
