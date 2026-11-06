using System;
using System.Net;
using UnityEngine.Networking;
using UnityEngine.Networking.Types;

namespace RoR2Arm64
{
    // Supports the existing HLAPI LocalClient/ULocalConnection path only.
    // No socket, relay, discovery or remote connection is implemented.
    public sealed class ManagedSoloTransport : INetworkTransport
    {
        private const byte Unsupported = (byte)NetworkError.WrongOperation;
        private bool started;

        public bool IsStarted { get { return started; } }
        public void Init() { started = true; }
        public void Init(GlobalConfig config) { Init(); }
        public void Shutdown() { started = false; }

        private static NotSupportedException RemoteHostNotSupported()
        {
            return new NotSupportedException("ARM64 solo transport supports only HLAPI LocalClient with NetworkServer.dontListen=true. Remote hosts, sockets and relays are not implemented.");
        }

        public int AddHost(HostTopology topology, int port, string ip) { throw RemoteHostNotSupported(); }
        public int AddWebsocketHost(HostTopology topology, int port, string ip) { throw RemoteHostNotSupported(); }
        public int AddHostWithSimulator(HostTopology topology, int minTimeout, int maxTimeout, int port) { throw RemoteHostNotSupported(); }
        public bool RemoveHost(int hostId) { return false; }

        public int Connect(int hostId, string address, int port, int specialConnectionId, out byte error)
        {
            error = Unsupported;
            return -1;
        }

        public int ConnectWithSimulator(int hostId, string address, int port, int specialConnectionId, out byte error, ConnectionSimulatorConfig conf)
        {
            error = Unsupported;
            return -1;
        }

        public void ConnectAsNetworkHost(int hostId, string address, int port, NetworkID network, SourceID source, NodeID node, out byte error)
        {
            error = Unsupported;
        }

        public int ConnectToNetworkPeer(int hostId, string address, int port, int specialConnectionId, int relaySlotId, NetworkID network, SourceID source, NodeID node, out byte error)
        {
            error = Unsupported;
            return -1;
        }

        public int ConnectEndPoint(int hostId, EndPoint endPoint, int specialConnectionId, out byte error)
        {
            error = Unsupported;
            return -1;
        }

        public bool DoesEndPointUsePlatformProtocols(EndPoint endPoint) { return false; }
        public bool Disconnect(int hostId, int connectionId, out byte error) { error = Unsupported; return false; }
        public bool Send(int hostId, int connectionId, int channelId, byte[] buffer, int size, out byte error) { error = Unsupported; return false; }

        public NetworkEventType Receive(out int hostId, out int connectionId, out int channelId, byte[] buffer, int bufferSize, out int receivedSize, out byte error)
        {
            hostId = -1;
            connectionId = -1;
            channelId = -1;
            receivedSize = 0;
            error = Unsupported;
            return NetworkEventType.Nothing;
        }

        public NetworkEventType ReceiveFromHost(int hostId, out int connectionId, out int channelId, byte[] buffer, int bufferSize, out int receivedSize, out byte error)
        {
            connectionId = -1;
            channelId = -1;
            receivedSize = 0;
            error = Unsupported;
            return NetworkEventType.Nothing;
        }

        public NetworkEventType ReceiveRelayEventFromHost(int hostId, out byte error) { error = Unsupported; return NetworkEventType.Nothing; }
        public int GetCurrentRTT(int hostId, int connectionId, out byte error) { error = Unsupported; return 0; }

        public void GetConnectionInfo(int hostId, int connectionId, out string address, out int port, out NetworkID network, out NodeID dstNode, out byte error)
        {
            address = string.Empty;
            port = 0;
            network = default(NetworkID);
            dstNode = default(NodeID);
            error = Unsupported;
        }

        public void SetBroadcastCredentials(int hostId, int key, int version, int subversion, out byte error) { error = Unsupported; }
        public bool StartBroadcastDiscovery(int hostId, int broadcastPort, int key, int version, int subversion, byte[] buffer, int size, int timeout, out byte error) { error = Unsupported; return false; }
        public void GetBroadcastConnectionInfo(int hostId, out string address, out int port, out byte error) { address = string.Empty; port = 0; error = Unsupported; }
        public void GetBroadcastConnectionMessage(int hostId, byte[] buffer, int bufferSize, out int receivedSize, out byte error) { receivedSize = 0; error = Unsupported; }
        public void StopBroadcastDiscovery() { }
        public void SetPacketStat(int direction, int packetStatId, int numMsgs, int numBytes) { }
    }
}
