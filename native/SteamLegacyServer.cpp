#include <stdio.h>
#include "steam_api.h"
#include "steam_gameserver.h"

extern "C" void *Risk2MacSteamSymbol(const char *name);

extern "C" int Risk2MacSteamCheckLegacyInterfaces(void)
{
    typedef void *(*CreateInterface)(const char *);
    typedef int (*GetHandle)(void);
    CreateInterface create = reinterpret_cast<CreateInterface>(Risk2MacSteamSymbol("SteamInternal_CreateInterface"));
    GetHandle get_user = reinterpret_cast<GetHandle>(Risk2MacSteamSymbol("SteamAPI_GetHSteamUser"));
    GetHandle get_pipe = reinterpret_cast<GetHandle>(Risk2MacSteamSymbol("SteamAPI_GetHSteamPipe"));
    if (!create || !get_user || !get_pipe) return 0;
    ISteamClient *client = static_cast<ISteamClient *>(create(STEAMCLIENT_INTERFACE_VERSION));
    if (!client) return 0;
    HSteamUser user = get_user();
    HSteamPipe pipe = get_pipe();
    return user && pipe &&
        client->GetISteamUser(user, pipe, STEAMUSER_INTERFACE_VERSION) &&
        client->GetISteamFriends(user, pipe, STEAMFRIENDS_INTERFACE_VERSION) &&
        client->GetISteamUtils(pipe, STEAMUTILS_INTERFACE_VERSION) &&
        client->GetISteamMatchmaking(user, pipe, STEAMMATCHMAKING_INTERFACE_VERSION) &&
        client->GetISteamMatchmakingServers(user, pipe, STEAMMATCHMAKINGSERVERS_INTERFACE_VERSION) &&
        client->GetISteamUserStats(user, pipe, STEAMUSERSTATS_INTERFACE_VERSION) &&
        client->GetISteamApps(user, pipe, STEAMAPPS_INTERFACE_VERSION) &&
        client->GetISteamNetworking(user, pipe, STEAMNETWORKING_INTERFACE_VERSION) &&
        client->GetISteamRemoteStorage(user, pipe, STEAMREMOTESTORAGE_INTERFACE_VERSION) &&
        client->GetISteamScreenshots(user, pipe, STEAMSCREENSHOTS_INTERFACE_VERSION) &&
        client->GetISteamHTTP(user, pipe, STEAMHTTP_INTERFACE_VERSION) &&
        client->GetISteamUGC(user, pipe, STEAMUGC_INTERFACE_VERSION) &&
        client->GetISteamAppList(user, pipe, STEAMAPPLIST_INTERFACE_VERSION) &&
        client->GetISteamInventory(user, pipe, STEAMINVENTORY_INTERFACE_VERSION);
}

extern "C" bool Risk2MacLegacy_SteamInternal_GameServer_Init(uint32 address,
    uint16 steam_port, uint16 game_port, uint16 query_port, int mode, const char *version)
{
    typedef bool (*LegacyInitialize)(uint32, uint16, uint16, uint16, int, const char *);
    LegacyInitialize legacy = reinterpret_cast<LegacyInitialize>(Risk2MacSteamSymbol("SteamInternal_GameServer_Init"));
    if (legacy) return legacy(address, steam_port, game_port, query_port, mode, version);

    // The current API manages its own Steam connection and accepts only the game
    // and query ports. Ask it to verify every interface used by the old wrapper.
    typedef int (*InitializeV2)(uint32, uint16, uint16, int, const char *, const char *, char *);
    InitializeV2 initialize = reinterpret_cast<InitializeV2>(Risk2MacSteamSymbol("SteamInternal_GameServer_Init_V2"));
    if (!initialize) return false;
    const char interfaces[] =
        STEAMUTILS_INTERFACE_VERSION "\0"
        STEAMGAMESERVER_INTERFACE_VERSION "\0"
        STEAMGAMESERVERSTATS_INTERFACE_VERSION "\0"
        STEAMHTTP_INTERFACE_VERSION "\0"
        STEAMINVENTORY_INTERFACE_VERSION "\0"
        STEAMNETWORKING_INTERFACE_VERSION "\0"
        STEAMUGC_INTERFACE_VERSION "\0\0";
    char error[1024] = {0};
    int result = initialize(address, game_port, query_port, mode, version, interfaces, error);
    if (result != 0)
        fprintf(stderr, "RISK2MAC_STEAM_SERVER_FAILED: result=%d error=%s\n", result, error);
    return result == 0;
}
