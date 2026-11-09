#include <CoreFoundation/CoreFoundation.h>
#include <Security/Security.h>
#include <dlfcn.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Load Valve's installed client libraries without redistributing them. */
static void *steam_api;
static char api_path[PATH_MAX];
static char client_path[PATH_MAX];
static int validation = -1;
static int available = -1;
static const uint32_t app_id = 632360;
extern int Risk2MacSteamCheckLegacyInterfaces(void);

static bool validate_valve_signature(const char *path)
{
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL,
        (const UInt8 *)path, (CFIndex)strlen(path), false);
    SecStaticCodeRef code = NULL;
    SecRequirementRef requirement = NULL;
    const void *keys[] = { kSecCodeAttributeArchitecture };
#if defined(__arm64__)
    const void *values[] = { CFSTR("arm64") };
#else
    const void *values[] = { CFSTR("x86_64") };
#endif
    CFDictionaryRef attributes = CFDictionaryCreate(NULL, keys, values, 1,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    OSStatus status = url ? SecStaticCodeCreateWithPathAndAttributes(url, kSecCSDefaultFlags, attributes, &code) : errSecParam;
    if (status == errSecSuccess)
        status = SecRequirementCreateWithString(CFSTR("anchor apple generic and certificate leaf[subject.OU] = \"MXGJJ98X76\""),
            kSecCSDefaultFlags, &requirement);
    if (status == errSecSuccess)
        status = SecStaticCodeCheckValidity(code, kSecCSDefaultFlags, requirement);
    if (attributes) CFRelease(attributes);
    if (requirement) CFRelease(requirement);
    if (code) CFRelease(code);
    if (url) CFRelease(url);
    if (status != errSecSuccess)
        fprintf(stderr, "RISK2MAC_STEAM_SIGNATURE_FAILED: status=%d path=%s\n", (int)status, path);
    return status == errSecSuccess;
}

int Risk2MacSteamValidateApi(void)
{
    if (validation >= 0) return validation;
    validation = 0;
    const char *home = getenv("HOME");
    if (!home || !*home) return 0;
    const char *base = "/Library/Application Support/Steam/Steam.AppBundle/Steam/Contents/MacOS";
    const char *configured_api = getenv("RISK2MAC_STEAM_API");
    int api_length = configured_api && *configured_api
        ? snprintf(api_path, sizeof(api_path), "%s", configured_api)
        : snprintf(api_path, sizeof(api_path), "%s%s/Frameworks/Steam Helper.app/Contents/MacOS/libsteam_api.dylib", home, base);
    int client_length = snprintf(client_path, sizeof(client_path), "%s%s/steamclient.dylib", home, base);
    if (api_length < 0 || api_length >= (int)sizeof(api_path) ||
        client_length < 0 || client_length >= (int)sizeof(client_path)) return 0;
    if (!validate_valve_signature(api_path) || !validate_valve_signature(client_path)) return 0;
    steam_api = dlopen(api_path, RTLD_NOW | RTLD_GLOBAL);
    if (!steam_api) {
        fprintf(stderr, "RISK2MAC_STEAM_LIBRARY_FAILED: %s\n", dlerror());
        return 0;
    }
    validation = 1;
    return 1;
}

const char *Risk2MacSteamApiPath(void)
{
    return Risk2MacSteamValidateApi() ? api_path : NULL;
}

void *Risk2MacSteamSymbol(const char *name)
{
    return Risk2MacSteamValidateApi() ? dlsym(steam_api, name) : NULL;
}

bool Risk2MacSteamApiInit(void)
{
    if (!Risk2MacSteamValidateApi()) return false;
    bool (*initialize)(void) = (bool (*)(void))dlsym(steam_api, "SteamAPI_InitSafe");
    if (!initialize) return false;
    setenv("SteamAppId", "632360", 1);
    setenv("SteamGameId", "632360", 1);
    return initialize();
}

int Risk2MacSteamInitialize(void)
{
    if (available >= 0) return available;
    available = 0;
    if (!Risk2MacSteamApiInit()) {
        fprintf(stderr, "RISK2MAC_STEAM_UNAVAILABLE: initialization failed\n");
        return 0;
    }
    void *(*apps_interface)(void) = (void *(*)(void))dlsym(steam_api, "SteamAPI_SteamApps_v009");
    if (!apps_interface)
        apps_interface = (void *(*)(void))dlsym(steam_api, "SteamAPI_SteamApps_v008");
    void *(*user_interface)(void) = (void *(*)(void))dlsym(steam_api, "SteamAPI_SteamUser_v023");
    if (!user_interface)
        user_interface = (void *(*)(void))dlsym(steam_api, "SteamAPI_SteamUser_v022");
    if (!user_interface)
        user_interface = (void *(*)(void))dlsym(steam_api, "SteamAPI_SteamUser_v021");
    bool (*subscribed)(void *, uint32_t) = (bool (*)(void *, uint32_t))dlsym(steam_api, "SteamAPI_ISteamApps_BIsSubscribedApp");
    bool (*logged_on)(void *) = (bool (*)(void *))dlsym(steam_api, "SteamAPI_ISteamUser_BLoggedOn");
    void *apps = apps_interface ? apps_interface() : NULL;
    void *user = user_interface ? user_interface() : NULL;
    if (apps && user && subscribed && logged_on && subscribed(apps, app_id) && logged_on(user) &&
        Risk2MacSteamCheckLegacyInterfaces()) {
        available = 1;
        fprintf(stderr, "RISK2MAC_STEAM_READY: genuine client and game subscription verified\n");
    } else {
        void (*shutdown)(void) = (void (*)(void))dlsym(steam_api, "SteamAPI_Shutdown");
        if (shutdown) shutdown();
        fprintf(stderr, "RISK2MAC_STEAM_UNAVAILABLE: subscription, signed-in account, or legacy interfaces unavailable\n");
    }
    return available;
}
