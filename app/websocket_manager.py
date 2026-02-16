from fastapi import WebSocket
from typing import Dict, List
import asyncio
from datetime import datetime
import secrets
import string

class ConnectionManager:
    def __init__(self):
        # Room management
        self.rooms_students: Dict[str, Dict[str, WebSocket]] = {}
        self.rooms_teachers: Dict[str, List[WebSocket]] = {}
        self.rooms_students_info: Dict[str, Dict[str, dict]] = {}

        # Reverse mappings
        self.teacher_rooms: Dict[WebSocket, str] = {}
        self.teacher_names: Dict[WebSocket, str] = {}
        
        # WebRTC Audio - user_id to websocket mapping
        self.user_websockets: Dict[str, WebSocket] = {}  # user_id -> websocket
        self.websocket_users: Dict[WebSocket, str] = {}  # websocket -> user_id

        # Room ID storage
        self.room_ids: Dict[str, str] = {}
        self.used_room_codes = set()

        # Thread safety
        self.lock = asyncio.Lock()

        print("✅ ConnectionManager initialized with WebRTC support")

    def generate_room_id(self) -> str:
        """Generate unique 6-character room code"""
        characters = string.ascii_uppercase + string.digits
        max_attempts = 100
        attempts = 0
        
        while attempts < max_attempts:
            room_id = ''.join(secrets.choice(characters) for _ in range(6))
            if room_id not in self.used_room_codes and room_id not in self.rooms_teachers:
                self.used_room_codes.add(room_id)
                print(f"🎲 Generated NEW unique room ID: {room_id}")
                return room_id
            attempts += 1
        
        raise Exception("Unable to generate unique room code")

    async def connect_teacher(self, websocket: WebSocket, teacher_name: str = "Teacher") -> str:
        """Connect a teacher and create/initialize a room"""
        await websocket.accept()

        async with self.lock:
            room_id = self.generate_room_id()
            
            self.rooms_teachers[room_id] = [websocket]
            self.rooms_students[room_id] = {}
            self.rooms_students_info[room_id] = {}
            self.room_ids[room_id] = room_id
            
            self.teacher_rooms[websocket] = room_id
            self.teacher_names[websocket] = teacher_name
            
            # Track teacher for WebRTC
            teacher_id = f"teacher_{room_id}"
            self.user_websockets[teacher_id] = websocket
            self.websocket_users[websocket] = teacher_id
            
            print(f"🏫 Created NEW room {room_id}")
            print(f"✅ Teacher '{teacher_name}' connected to room {room_id}")

        await websocket.send_json({
            "type": "room_created",
            "data": {
                "room_id": room_id,
                "teacher_name": teacher_name,
                "timestamp": datetime.now().isoformat()
            }
        })

        return room_id

    async def connect_student(self, websocket: WebSocket, room_id: str, student_id: str, student_name: str) -> bool:
        """Connect a student to a room"""
        await websocket.accept()

        async with self.lock:
            if room_id not in self.rooms_students:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Room {room_id} does not exist"
                })
                await websocket.close(code=4004, reason="Room not found")
                print(f"❌ Room {room_id} not found for student {student_name}")
                return False

            if room_id not in self.rooms_teachers or len(self.rooms_teachers[room_id]) == 0:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Room {room_id} has no active teachers"
                })
                await websocket.close(code=4004, reason="No teachers in room")
                print(f"❌ Room {room_id} has no teachers for student {student_name}")
                return False

            self.rooms_students[room_id][student_id] = websocket
            self.rooms_students_info[room_id][student_id] = {
                "id": student_id,
                "name": student_name,
                "status": "attentive",
                "last_update": datetime.now().isoformat(),
                "alerts_count": 0
            }
            
            # Track student for WebRTC
            self.user_websockets[student_id] = websocket
            self.websocket_users[websocket] = student_id

            print(f"✅ Student '{student_name}' ({student_id[:8]}...) added to room {room_id}")

        await self.broadcast_to_room_students(room_id, {
            "type": "student_join",
            "data": {
                "student_id": student_id,
                "student_name": student_name,
                "timestamp": datetime.now().isoformat()
            }
        }, exclude_id=student_id)

        students_list = list(self.rooms_students_info[room_id].values())
        await self.broadcast_to_room_teachers(room_id, {
            "type": "student_join",
            "data": {
                "student_id": student_id,
                "student_name": student_name,
                "students": students_list,
                "timestamp": datetime.now().isoformat()
            }
        })

        return True

    async def disconnect_student(self, room_id: str, student_id: str):
        """Disconnect a student from a room"""
        student_name = "Unknown"

        async with self.lock:
            if room_id in self.rooms_students_info and student_id in self.rooms_students_info[room_id]:
                student_name = self.rooms_students_info[room_id][student_id]["name"]
                del self.rooms_students_info[room_id][student_id]

            if room_id in self.rooms_students and student_id in self.rooms_students[room_id]:
                ws = self.rooms_students[room_id][student_id]
                del self.rooms_students[room_id][student_id]
                
                # Clean up WebRTC mappings
                if ws in self.websocket_users:
                    del self.websocket_users[ws]
                if student_id in self.user_websockets:
                    del self.user_websockets[student_id]

        print(f"❌ Student '{student_name}' left room {room_id}")

        await self.broadcast_to_room_students(room_id, {
            "type": "student_leave",
            "data": {
                "student_id": student_id,
                "student_name": student_name,
                "timestamp": datetime.now().isoformat()
            }
        })

        students_list = list(self.rooms_students_info.get(room_id, {}).values())
        await self.broadcast_to_room_teachers(room_id, {
            "type": "student_leave",
            "data": {
                "student_id": student_id,
                "student_name": student_name,
                "students": students_list,
                "timestamp": datetime.now().isoformat()
            }
        })
        
        # Notify about audio disconnection
        await self.broadcast_to_room(room_id, {
            "type": "audio_user_left",
            "from_user": student_id
        })

    async def disconnect_teacher(self, websocket: WebSocket):
        """Disconnect a teacher"""
        async with self.lock:
            room_id = self.teacher_rooms.get(websocket)

            if not room_id:
                print("⚠️ Teacher disconnect called but no room_id found")
                if websocket in self.teacher_rooms:
                    del self.teacher_rooms[websocket]
                if websocket in self.teacher_names:
                    del self.teacher_names[websocket]
                if websocket in self.websocket_users:
                    user_id = self.websocket_users[websocket]
                    del self.websocket_users[websocket]
                    if user_id in self.user_websockets:
                        del self.user_websockets[user_id]
                return

            if room_id in self.rooms_teachers:
                if websocket in self.rooms_teachers[room_id]:
                    self.rooms_teachers[room_id].remove(websocket)
                    teacher_name = self.teacher_names.get(websocket, "Unknown Teacher")
                    print(f"👨‍🏫 Teacher '{teacher_name}' left room {room_id}")

                if len(self.rooms_teachers[room_id]) == 0:
                    print(f"🚪 CLOSING ROOM {room_id} - Last teacher disconnected")

                    students_to_close = list(self.rooms_students.get(room_id, {}).values())
                    for student_ws in students_to_close:
                        try:
                            await student_ws.send_json({
                                "type": "room_closed",
                                "message": "Teacher has ended the class"
                            })
                            await student_ws.close(code=4003, reason="Room closed")
                        except Exception as e:
                            print(f"❌ Error notifying student: {e}")

                    if room_id in self.rooms_teachers:
                        del self.rooms_teachers[room_id]
                    if room_id in self.rooms_students:
                        del self.rooms_students[room_id]
                    if room_id in self.rooms_students_info:
                        del self.rooms_students_info[room_id]
                    if room_id in self.room_ids:
                        del self.room_ids[room_id]
                    if room_id in self.used_room_codes:
                        self.used_room_codes.remove(room_id)

            if websocket in self.teacher_rooms:
                del self.teacher_rooms[websocket]
            if websocket in self.teacher_names:
                del self.teacher_names[websocket]
            if websocket in self.websocket_users:
                user_id = self.websocket_users[websocket]
                del self.websocket_users[websocket]
                if user_id in self.user_websockets:
                    del self.user_websockets[user_id]

    # ==================== WEBRTC AUDIO METHODS ====================
    
    async def handle_audio_message(self, websocket: WebSocket, room_id: str, message: dict):
        """Handle WebRTC audio signaling messages"""
        msg_type = message.get("type")
        user_id = self.websocket_users.get(websocket)
        
        if not user_id:
            print("⚠️ Audio message from unknown user")
            return
        
        print(f"🎤 Audio message: {msg_type} from {user_id[:8]}...")
        
        if msg_type == "audio_ready":
            # User enabled audio - notify others in room
            await self.broadcast_to_room(room_id, {
                "type": "audio_user_joined",
                "from_user": user_id
            }, exclude=websocket)
            
        elif msg_type == "audio_offer":
            # Forward offer to target user
            to_user = message.get("to_user")
            offer = message.get("offer")
            await self.send_to_user(to_user, {
                "type": "audio_offer",
                "from_user": user_id,
                "offer": offer
            })
            
        elif msg_type == "audio_answer":
            # Forward answer to target user
            to_user = message.get("to_user")
            answer = message.get("answer")
            await self.send_to_user(to_user, {
                "type": "audio_answer",
                "from_user": user_id,
                "answer": answer
            })
            
        elif msg_type == "audio_ice_candidate":
            # Forward ICE candidate to target user
            to_user = message.get("to_user")
            candidate = message.get("candidate")
            await self.send_to_user(to_user, {
                "type": "audio_ice_candidate",
                "from_user": user_id,
                "candidate": candidate
            })
            
        elif msg_type == "audio_stopped":
            # User disabled audio
            await self.broadcast_to_room(room_id, {
                "type": "audio_user_left",
                "from_user": user_id
            }, exclude=websocket)
            
        elif msg_type == "audio_speaking":
            # User is speaking
            level = message.get("level", 0)
            await self.broadcast_to_room(room_id, {
                "type": "audio_speaking",
                "from_user": user_id,
                "level": level
            }, exclude=websocket)
    
    async def send_to_user(self, user_id: str, message: dict):
        """Send message to specific user by ID"""
        if user_id in self.user_websockets:
            try:
                await self.user_websockets[user_id].send_json(message)
                print(f"📤 Sent {message['type']} to {user_id[:8]}...")
            except Exception as e:
                print(f"❌ Error sending to {user_id[:8]}...: {e}")
        else:
            print(f"⚠️ User {user_id[:8]}... not found for message {message['type']}")
    
    async def broadcast_to_room(self, room_id: str, message: dict, exclude: WebSocket = None):
        """Broadcast message to everyone in room (teachers + students)"""
        sent_count = 0
        
        # Send to teachers
        if room_id in self.rooms_teachers:
            for teacher_ws in self.rooms_teachers[room_id]:
                if teacher_ws != exclude:
                    try:
                        await teacher_ws.send_json(message)
                        sent_count += 1
                    except Exception as e:
                        print(f"❌ Error broadcasting to teacher: {e}")
        
        # Send to students
        if room_id in self.rooms_students:
            for student_ws in self.rooms_students[room_id].values():
                if student_ws != exclude:
                    try:
                        await student_ws.send_json(message)
                        sent_count += 1
                    except Exception as e:
                        print(f"❌ Error broadcasting to student: {e}")
        
        if sent_count > 0:
            print(f"📤 Broadcast {message['type']} to {sent_count} users in room {room_id}")
    
    def get_room_by_websocket(self, websocket: WebSocket) -> str:
        """Get room ID from websocket"""
        # Check if teacher
        if websocket in self.teacher_rooms:
            return self.teacher_rooms[websocket]
        
        # Check if student
        for room_id, students in self.rooms_students.items():
            if websocket in students.values():
                return room_id
        
        return None

    # ==================== EXISTING METHODS ====================

    async def broadcast_to_room_teachers(self, room_id: str, message: dict):
        """Broadcast message to all teachers in a room"""
        if room_id not in self.rooms_teachers:
            return

        disconnected = []
        
        for teacher_ws in self.rooms_teachers[room_id]:
            try:
                await teacher_ws.send_json(message)
            except Exception as e:
                print(f"❌ Error sending to teacher: {e}")
                disconnected.append(teacher_ws)

        for teacher_ws in disconnected:
            await self.disconnect_teacher(teacher_ws)

    async def broadcast_to_room_students(self, room_id: str, message: dict, exclude_id: str = None):
        """Broadcast message to all students in a room"""
        if room_id not in self.rooms_students:
            return

        disconnected = []

        for student_id, student_ws in self.rooms_students[room_id].items():
            if exclude_id and student_id == exclude_id:
                continue

            try:
                await student_ws.send_json(message)
            except Exception as e:
                print(f"❌ Error sending to student: {e}")
                disconnected.append(student_id)

        for student_id in disconnected:
            await self.disconnect_student(room_id, student_id)

    async def update_student_attention(self, room_id: str, student_id: str, attention_data: dict):
        """Update student's attention status and notify teachers"""
        async with self.lock:
            if room_id in self.rooms_students_info and student_id in self.rooms_students_info[room_id]:
                student_info = self.rooms_students_info[room_id][student_id]
                student_info["status"] = attention_data.get("status", "attentive")
                student_info["last_update"] = datetime.now().isoformat()

        await self.broadcast_to_room_teachers(room_id, {
            "type": "attention_update",
            "data": {
                "student_id": student_id,
                "student_name": self.rooms_students_info[room_id][student_id]["name"],
                "status": attention_data.get("status"),
                "confidence": attention_data.get("confidence", 0.0),
                "timestamp": datetime.now().isoformat()
            }
        })

    async def send_to_student(self, room_id: str, student_id: str, message: dict):
        """Send message to specific student"""
        if room_id in self.rooms_students and student_id in self.rooms_students[room_id]:
            try:
                await self.rooms_students[room_id][student_id].send_json(message)
            except Exception as e:
                print(f"❌ Error sending to student: {e}")

    async def broadcast_camera_frame(self, room_id: str, student_id: str, frame_data: str):
        """Broadcast student's camera frame to teachers"""
        if room_id not in self.rooms_teachers:
            return

        message = {
            "type": "camera_frame",
            "data": {
                "student_id": student_id,
                "frame": frame_data,
                "timestamp": datetime.now().isoformat()
            }
        }

        await self.broadcast_to_room_teachers(room_id, message)

    def room_exists(self, room_id: str) -> bool:
        """Check if a room exists and has at least one teacher"""
        exists = room_id in self.rooms_teachers and len(self.rooms_teachers[room_id]) > 0
        return exists

    def get_room_info(self, room_id: str) -> dict:
        """Get detailed information about a room"""
        if not self.room_exists(room_id):
            return None

        return {
            "room_id": room_id,
            "teachers_count": len(self.rooms_teachers.get(room_id, [])),
            "students_count": len(self.rooms_students.get(room_id, {})),
            "students": list(self.rooms_students_info.get(room_id, {}).values())
        }

# Global manager instance
manager = ConnectionManager()
print("=" * 60)
print("✅ Global ConnectionManager with WebRTC support created")
print("=" * 60)