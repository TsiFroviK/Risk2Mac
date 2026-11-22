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
    const char *user_getters[] = {
        "SteamAPI_SteamUser_v024", "SteamAPI_SteamUser_v023",
        "SteamAPI_SteamUser_v022", "SteamAPI_SteamUser_v021",
    };
    void *user = NULL;
    for (size_t i = 0; !user && i < sizeof(user_getters) / sizeof(user_getters[0]); ++i) {
        void *(*user_interface)(void) = (void *(*)(void))dlsym(steam_api, user_getters[i]);
        if (user_interface) user = user_interface();
    }
    bool (*subscribed)(void *, uint32_t) = (bool (*)(void *, uint32_t))dlsym(steam_api, "SteamAPI_ISteamApps_BIsSubscribedApp");
    bool (*logged_on)(void *) = (bool (*)(void *))dlsym(steam_api, "SteamAPI_ISteamUser_BLoggedOn");
    void *apps = apps_interface ? apps_interface() : NULL;
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

static void *achievement_stats(void)
{
    if (available != 1) return NULL;
    /* Pair the versioned getter and flat calls from the same installed library. */
    const char *getters[] = { "SteamAPI_SteamUserStats_v013", "SteamAPI_SteamUserStats_v012" };
    for (size_t i = 0; i < sizeof(getters) / sizeof(getters[0]); ++i) {
        void *(*get)(void) = (void *(*)(void))dlsym(steam_api, getters[i]);
        if (get) return get();
    }
    return NULL;
}

enum AchievementResult {
    AchievementRetry,
    AchievementAlreadyUnlocked,
    AchievementStaged,
    AchievementUnknown,
};

int Risk2MacSteamStageAchievement(const char *name)
{
    void *stats = achievement_stats();
    if (!stats) return AchievementRetry;

    bool (*get)(void *, const char *, bool *) =
        (bool (*)(void *, const char *, bool *))dlsym(steam_api, "SteamAPI_ISteamUserStats_GetAchievement");
    bool (*set)(void *, const char *) =
        (bool (*)(void *, const char *))dlsym(steam_api, "SteamAPI_ISteamUserStats_SetAchievement");
    if (!get || !set) return AchievementRetry;

    bool unlocked = false;
    if (get(stats, name, &unlocked)) {
        if (unlocked) return AchievementAlreadyUnlocked;
        return set(stats, name) ? AchievementStaged : AchievementRetry;
    }

    /* Ignore mod-only IDs once Steam has loaded its achievement catalogue. */
    uint32_t (*count)(void *) =
        (uint32_t (*)(void *))dlsym(steam_api, "SteamAPI_ISteamUserStats_GetNumAchievements");
    const char *(*achievement_name)(void *, uint32_t) =
        (const char *(*)(void *, uint32_t))dlsym(steam_api, "SteamAPI_ISteamUserStats_GetAchievementName");
    uint32_t total = count ? count(stats) : 0;
    if (!total || !achievement_name) return AchievementRetry;
    for (uint32_t i = 0; i < total; ++i) {
        const char *entry = achievement_name(stats, i);
        if (!entry || !*entry || strcmp(entry, name) == 0) return AchievementRetry;
    }
    return AchievementUnknown;
}

int Risk2MacSteamStoreAchievements(void)
{
    void *stats = achievement_stats();
    if (!stats) return 0;
    bool (*store)(void *) =
        (bool (*)(void *))dlsym(steam_api, "SteamAPI_ISteamUserStats_StoreStats");
    return store && store(stats);
}
