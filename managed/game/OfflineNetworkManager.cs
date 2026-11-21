using System;
using System.Collections.Generic;
using RoR2;
using RoR2.Networking;
using UnityEngine;
using UnityEngine.Networking;
using PlatformID = RoR2.PlatformID;

namespace RoR2Arm64.Offline
{
    public sealed class OfflineNetworkManager : NetworkManagerSystem
    {
        private static NotSupportedException RemoteUnavailable() { return new NotSupportedException("This prototype supports only single-player HLAPI LocalClient; no Steam/EOS/IP multiplayer."); }
        protected override void Start()
        {
            foreach (QosType channel in channels) connectionConfig.AddChannel(channel);
            connectionConfig.PacketSize = 1200;
            clientP2PId = OfflinePlatform.LocalIdentity;
            serverP2PId = OfflinePlatform.LocalIdentity;
            StartCoroutine(FireOnStartGlobalEvent());
        }
        protected override void Update()
        {
            UpdateTime(ref _unpredictedServerFrameTime, ref _unpredictedServerFrameTimeSmoothed, ref unpredictedServerFrameTimeVelocity, Time.deltaTime);
            EnsureDesiredHost();
            UpdateClient();
        }
        protected override void EnsureDesiredHost()
        {
            if (serverShuttingDown || clientIsConnecting || isLoadingScene || !SystemInitializerAttribute.hasExecuted) return;
            if (desiredHost.isRemote) { desiredHost = HostDescription.none; throw RemoteUnavailable(); }
            if (isNetworkActive && !actedUponDesiredHost && !desiredHost.DescribesCurrentHost()) { Disconnect(); return; }
            if (actedUponDesiredHost || desiredHost.hostType != HostDescription.HostType.Self || NetworkServer.active) return;
            if (desiredHost.hostingParameters.listen) { desiredHost = HostDescription.none; throw RemoteUnavailable(); }
            if (!LocalUserManager.isAnyUserSignedIn) return;
            actedUponDesiredHost = true;
            maxConnections = Math.Max(1, Math.Min(desiredHost.hostingParameters.maxPlayers, RoR2Application.maxLocalPlayers));
            NetworkServer.dontListen = true;
            isSinglePlayer = true;
            if (StartHost(connectionConfig, maxConnections) == null)
            {
                actedUponDesiredHost = false;
                throw new InvalidOperationException("HLAPI local host did not start.");
            }
        }
        public override void InitPlatformServer() { NetworkServer.dontListen = true; }
        public override void ForceCloseAllConnections() { }
        public override NetworkConnection GetClient(PlatformID id)
        {
            if (id != OfflinePlatform.LocalIdentity || !NetworkServer.active) return null;
            foreach (NetworkConnection connection in NetworkServer.connections) if (connection != null && Util.ConnectionIsLocal(connection)) return connection;
            return null;
        }
        public override void OnServerConnect(NetworkConnection connection)
        {
            if (!Util.ConnectionIsLocal(connection)) { connection.Disconnect(); throw RemoteUnavailable(); }
            base.OnServerConnect(connection);
            FireServerConnectGlobalEvent(connection);
        }
        public override void OnServerDisconnect(NetworkConnection connection) { FireServerDisconnectGlobalEvent(connection); base.OnServerDisconnect(connection); }
        public override void ServerHandleClientDisconnect(NetworkConnection connection) { OnServerDisconnect(connection); connection.Disconnect(); connection.Dispose(); }
        public override void ServerBanClient(NetworkConnection connection) { throw RemoteUnavailable(); }
        protected override void KickClient(NetworkConnection connection, BaseKickReason reason) { connection.Disconnect(); }
        protected override NetworkUserId AddPlayerIdFromPlatform(NetworkConnection connection, AddPlayerMessage message, byte playerControllerId) { return NetworkUserId.FromId(OfflinePlatform.LocalIdentity.ID, playerControllerId); }
        protected override AddPlayerMessage CreateClientAddPlayerMessage() { return new AddPlayerMessage { id = OfflinePlatform.LocalIdentity, steamAuthTicketData = new byte[0] }; }
        protected override void PlatformAuth(ref ClientAuthData data, NetworkConnection connection)
        {
            if (!Util.ConnectionIsLocal(connection)) throw RemoteUnavailable();
            data.platformId = OfflinePlatform.LocalIdentity;
            data.authTicket = new byte[0];
            data.entitlements = new string[0];
        }
        protected override void UpdateCheckInactiveConnections() { }
        protected override void UpdateServer() { }
        protected override void StartClient(PlatformID id) { throw RemoteUnavailable(); }
        public override bool IsConnectedToServer(PlatformID id) { return id == OfflinePlatform.LocalIdentity && client != null && client.isConnected && Util.ConnectionIsLocal(client.connection); }
        public override void CreateLocalLobby() { NetworkServer.dontListen = true; }
        public override IEnumerator<CanPlayOnlineState> CanPlayOnline() { yield return CanPlayOnlineState.No; }
        protected override void PlatformClientSetPlayers(ConCommandArgs args) { if (client != null && client.connection != null) ClientSetPlayers(client.connection); }
        protected override void PlatformDisconnect(ConCommandArgs args) { desiredHost = HostDescription.none; }
        protected override void PlatformConnect(ConCommandArgs args) { throw RemoteUnavailable(); }
        protected override void PlatformConnectP2P(ConCommandArgs args) { throw RemoteUnavailable(); }
        protected override void PlatformHost(ConCommandArgs args)
        {
            if (args.GetArgBool(0)) throw RemoteUnavailable();
            desiredHost = new HostDescription(new HostDescription.HostingParameters { listen = false, maxPlayers = 1 });
        }
        protected override void PlatformGetP2PSessionState(ConCommandArgs args) { throw RemoteUnavailable(); }
        protected override void PlatformKick(ConCommandArgs args) { throw RemoteUnavailable(); }
        protected override void PlatformBan(ConCommandArgs args) { throw RemoteUnavailable(); }
    }
}
