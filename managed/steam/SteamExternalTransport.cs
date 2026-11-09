using System;
using System.Collections.Generic;
using System.Net;
using UnityEngine.Networking;
using UnityEngine.Networking.Types;

namespace Risk2Mac
{
    // HLAPI allocates host handles even for SteamNetworkClient and external
    // SteamNetworkConnection instances. Facepunch owns their packets and sessions.
    // This adapter supplies only that managed bookkeeping and never opens sockets.
    public sealed class SteamExternalTransport : INetworkTransport
    {
        private const byte Unsupported = (byte)NetworkError.WrongOperation;
        private readonly HashSet<int> hosts = new HashSet<int>();
        private readonly HashSet<int> rejectedConnections = new HashSet<int>();
        private readonly Action<string> warning;
        private int nextHostId;
        public bool IsStarted { get; private set; }

        public SteamExternalTransport() : this(null) { }
        public SteamExternalTransport(Action<string> warning) { this.warning = warning; }

        public void Init() { IsStarted = true; }
        public void Init(GlobalConfig config) { Init(); }
        public void Shutdown()
        {
            hosts.Clear();
            rejectedConnections.Clear();
            IsStarted = false;
        }

        public int AddHost(HostTopology topology, int port, string ip)
        {
            if (!IsStarted || topology == null || nextHostId == int.MaxValue) return -1;
            int hostId = nextHostId++;
            hosts.Add(hostId);
            return hostId;
        }

        public bool RemoveHost(int hostId)
        {
            rejectedConnections.Remove(hostId);
            return hosts.Remove(hostId);
        }

        public NetworkEventType ReceiveFromHost(int hostId, out int connectionId, out int channelId,
            byte[] buffer, int bufferSize, out int receivedSize, out byte error)
        {
            connectionId = -1;
            channelId = -1;
            receivedSize = 0;
            error = IsStarted && hosts.Contains(hostId) ? (byte)0 : Unsupported;
            if (error == 0 && rejectedConnections.Remove(hostId))
            {
                // HLAPI ignores Connect's immediate error. Surface that actual
                // failure once through its normal disconnect path, with no data.
                error = Unsupported;
                return NetworkEventType.DisconnectEvent;
            }
            return NetworkEventType.Nothing;
        }

        public NetworkEventType Receive(out int hostId, out int connectionId, out int channelId,
            byte[] buffer, int bufferSize, out int receivedSize, out byte error)
        {
            hostId = -1;
            connectionId = -1;
            channelId = -1;
            receivedSize = 0;
            error = IsStarted ? (byte)0 : Unsupported;
            foreach (int rejectedHost in rejectedConnections)
            {
                hostId = rejectedHost;
                break;
            }
            if (error == 0 && hostId >= 0)
            {
                rejectedConnections.Remove(hostId);
                error = Unsupported;
                return NetworkEventType.DisconnectEvent;
            }
            return NetworkEventType.Nothing;
        }

        public int AddWebsocketHost(HostTopology topology, int port, string ip) { return -1; }
        public int AddHostWithSimulator(HostTopology topology, int minTimeout, int maxTimeout, int port) { return -1; }
        public int Connect(int hostId, string address, int port, int specialConnectionId, out byte error)
        { return RejectConnection(hostId, out error); }
        public int ConnectWithSimulator(int hostId, string address, int port, int specialConnectionId, out byte error, ConnectionSimulatorConfig config)
        { return RejectConnection(hostId, out error); }
        public void ConnectAsNetworkHost(int hostId, string address, int port, NetworkID network, SourceID source, NodeID node, out byte error)
        { error = Unsupported; }
        public int ConnectToNetworkPeer(int hostId, string address, int port, int specialConnectionId, int relaySlotId, NetworkID network, SourceID source, NodeID node, out byte error)
        { return RejectConnection(hostId, out error); }
        public int ConnectEndPoint(int hostId, EndPoint endPoint, int specialConnectionId, out byte error)
        { return RejectConnection(hostId, out error); }
        private int RejectConnection(int hostId, out byte error)
        {
            error = Unsupported;
            if (IsStarted && hosts.Contains(hostId) && rejectedConnections.Add(hostId) && warning != null)
                warning("RISK2MAC_DIRECT_IP_UNSUPPORTED: Direct IP/UDP servers are unavailable in this Steam transport. Join a Steam P2P lobby instead.");
            return -1;
        }
        public bool DoesEndPointUsePlatformProtocols(EndPoint endPoint) { return false; }
        public bool Disconnect(int hostId, int connectionId, out byte error) { error = Unsupported; return false; }
        public bool Send(int hostId, int connectionId, int channelId, byte[] buffer, int size, out byte error)
        { error = Unsupported; return false; }
        public NetworkEventType ReceiveRelayEventFromHost(int hostId, out byte error)
        { error = Unsupported; return NetworkEventType.Nothing; }
        public int GetCurrentRTT(int hostId, int connectionId, out byte error)
        { error = Unsupported; return 0; }
        public void GetConnectionInfo(int hostId, int connectionId, out string address, out int port, out NetworkID network, out NodeID dstNode, out byte error)
        {
            address = string.Empty;
            port = 0;
            network = default(NetworkID);
            dstNode = default(NodeID);
            error = Unsupported;
        }
        public void SetBroadcastCredentials(int hostId, int key, int version, int subversion, out byte error)
        { error = Unsupported; }
        public bool StartBroadcastDiscovery(int hostId, int broadcastPort, int key, int version, int subversion, byte[] buffer, int size, int timeout, out byte error)
        { error = Unsupported; return false; }
        public void GetBroadcastConnectionInfo(int hostId, out string address, out int port, out byte error)
        { address = string.Empty; port = 0; error = Unsupported; }
        public void GetBroadcastConnectionMessage(int hostId, byte[] buffer, int bufferSize, out int receivedSize, out byte error)
        { receivedSize = 0; error = Unsupported; }
        public void StopBroadcastDiscovery() { }
        public void SetPacketStat(int direction, int packetStatId, int numMsgs, int numBytes) { }
    }
}
