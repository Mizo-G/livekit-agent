from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.agents.llm import function_tool
import logging
import json

logger = logging.getLogger("main")
load_dotenv(".env.local")

class Assistant(Agent):
    def __init__(self, rpc_context: dict = None) -> None:
        # Store context for RPC calls
        self.rpc_context = rpc_context or {}
        
        super().__init__(
            instructions="""You are a helpful voice AI assistant.
            You eagerly assist users with their questions by providing information from your extensive knowledge.
            
            IMPORTANT: You have a special capability to call RPC functions on the client. 
            When you want to trigger an action on the client (like showing a greeting), 
            use the send_greeting() function.
            
            Examples of when to use send_greeting():
            - User asks you to send a greeting to the client
            - User wants to trigger a UI action
            - User asks you to demonstrate RPC functionality
            
            Your responses are concise, to the point, and without any complex formatting or punctuation including emojis, asterisks, or other symbols.
            You are curious, friendly, and have a sense of humor.""",
        )
    
    @function_tool
    async def send_greeting(self, message: str = "Hello from the agent!"):
        """Send a greeting message to the client frontend via RPC.
        
        Args:
            message: The greeting message to send (default: "Hello from the agent!")
        """
        try:
            method = "client.greet"
            logger.info(f"Attempting to send RPC '{method}' with message: {message}")
            
            if not self.rpc_context.get('room'):
                logger.error("No room available in context")
                return "I can't send a greeting right now - no connection to client."
            
            room = self.rpc_context['room']
            remote_participants = list(room.remote_participants.values())
            
            if not remote_participants:
                logger.error("No remote participants found")
                return "I can't send a greeting - no client connected."
            
            client = remote_participants[0]
            logger.info(f"Sending RPC to client: {client.identity}")
            
            result = await room.local_participant.perform_rpc(
                destination_identity=client.identity,
                method=method,
                payload=json.dumps({"message": message, "from": "agent"})
            )
            
            logger.info(f"Successfully sent RPC '{method}' to frontend. Response: {result}")
            return f"Greeting sent to client: {message}"
            
        except Exception as e:
            logger.error(f"Failed to send RPC '{method}': {e}")
            return f"Failed to send greeting: {str(e)}"


server = AgentServer()

@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    session = AgentSession(
        stt="assemblyai/universal-streaming:en",
        llm="openai/gpt-4.1-mini",
        tts="cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

    await ctx.connect()

    p = await ctx.wait_for_participant()
    print(f"{p.identity} joined")
    
    # Store context for RPC
    rpc_context = {
        'room': ctx.room,
        'client_identity': p.identity
    }
    
    # Create agent with RPC context
    assistant = Assistant(rpc_context=rpc_context)
    
    # Test RPC call directly (optional - for debugging)
    try:
        print(f"Testing direct RPC call to: {p.identity}")
        response = await ctx.room.local_participant.perform_rpc(
            destination_identity=p.identity,
            method='client.greet',
            payload=json.dumps({"message": "Direct test from agent startup", "test": True})
        )
        print(f"Direct RPC response: {response}")
    except Exception as e:
        print(f"Direct RPC call failed: {e}")

    await session.start(
        room=ctx.room,
        agent=assistant,  # Pass our custom assistant
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
            ),
        ),
    )

    # Initial greeting that will trigger RPC when appropriate
    await session.generate_reply(
        instructions="""Greet the user and offer your assistance. 
        Tell them you can send greetings to their client if they ask.
        Example: "Hi! I'm your assistant. Try asking me to 'send a greeting to the client' or 'trigger a UI action'."
        """
    )

if __name__ == "__main__":
    agents.cli.run_app(server)
