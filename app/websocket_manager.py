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

        # Room ID storage - FIXED: Use set to track used IDs
        self.room_ids: Dict[str, str] = {}
        self.used_room_codes = set()  # Track all generated codes

        # Thread safety
        self.lock = asyncio.Lock()

        print("✅ ConnectionManager initialized")

    def generate_room_id(self) -> str:
        """
        Generate unique 6-character room code
        FIXED: Actually check against used codes
        """
        characters = string.ascii_uppercase + string.digits
        max_attempts = 100
        attempts = 0
        
        while attempts < max_attempts:
            room_id = ''.join(secrets.choice(characters) for _ in range(6))
            # Check if code is truly unique
            if room_id not in self.used_room_codes and room_id not in self.rooms_teachers:
                self.used_room_codes.add(room_id)
                print(f"🎲 Generated NEW unique room ID: {room_id}")
                return room_id
            attempts += 1
        
        # Fallback if somehow we can't generate unique code
        raise Exception("Unable to generate unique room code")

    async def connect_teacher(self, websocket: WebSocket, teacher_name: str = "Teacher") -> str:
        """
        Connect a teacher and create/initialize a room
        Returns the room_id for the teacher to share with students
        """
        await websocket.accept()

        async with self.lock:
            # Generate new room for this teacher
            room_id = self.generate_room_id()
            
            # Initialize room structures
            self.rooms_teachers[room_id] = [websocket]
            self.rooms_students[room_id] = {}
            self.rooms_students_info[room_id] = {}
            self.room_ids[room_id] = room_id
            
            # Track teacher
            self.teacher_rooms[websocket] = room_id
            self.teacher_names[websocket] = teacher_name
            
            print(f"🏫 Created NEW room {room_id}")
            print(f"✅ Teacher '{teacher_name}' connected to room {room_id}")
            print(f"👨‍🏫 Room {room_id} now has {len(self.rooms_teachers[room_id])} teacher(s)")

        # Send confirmation to teacher
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
            # Check if room exists
            if room_id not in self.rooms_students:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Room {room_id} does not exist"
                })
                await websocket.close(code=4004, reason="Room not found")
                print(f"❌ Room {room_id} not found for student {student_name}")
                return False

            # Check if room has active teachers
            if room_id not in self.rooms_teachers or len(self.rooms_teachers[room_id]) == 0:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Room {room_id} has no active teachers"
                })
                await websocket.close(code=4004, reason="No teachers in room")
                print(f"❌ Room {room_id} has no teachers for student {student_name}")
                return False

            # Add student to room
            self.rooms_students[room_id][student_id] = websocket
            self.rooms_students_info[room_id][student_id] = {
                "id": student_id,
                "name": student_name,
                "status": "attentive",
                "last_update": datetime.now().isoformat(),
                "alerts_count": 0
            }

            print(f"✅ Student '{student_name}' ({student_id[:8]}...) added to room {room_id}")
            print(f"📊 Room {room_id} now has {len(self.rooms_students[room_id])} student(s)")

        # Notify other students about new student
        await self.broadcast_to_room_students(room_id, {
            "type": "student_join",
            "data": {
                "student_id": student_id,
                "student_name": student_name,
                "timestamp": datetime.now().isoformat()
            }
        }, exclude_id=student_id)

        # CRITICAL FIX: Notify teachers about new student with full student list
        students_list = list(self.rooms_students_info[room_id].values())
        await self.broadcast_to_room_teachers(room_id, {
            "type": "student_join",
            "data": {
                "student_id": student_id,
                "student_name": student_name,
                "students": students_list,  # Send full list
                "timestamp": datetime.now().isoformat()
            }
        })
        print(f"📤 Sent student_join notification to teachers with {len(students_list)} students")

        return True

    async def disconnect_student(self, room_id: str, student_id: str):
        """Disconnect a student from a room"""
        student_name = "Unknown"

        async with self.lock:
            # Get student name before deletion
            if room_id in self.rooms_students_info and student_id in self.rooms_students_info[room_id]:
                student_name = self.rooms_students_info[room_id][student_id]["name"]
                del self.rooms_students_info[room_id][student_id]

            # Remove student WebSocket
            if room_id in self.rooms_students and student_id in self.rooms_students[room_id]:
                del self.rooms_students[room_id][student_id]

        print(f"❌ Student '{student_name}' left room {room_id}")
        print(f"📊 Room {room_id} now has {len(self.rooms_students.get(room_id, {}))} student(s)")

        # Notify other students
        await self.broadcast_to_room_students(room_id, {
            "type": "student_leave",
            "data": {
                "student_id": student_id,
                "student_name": student_name,
                "timestamp": datetime.now().isoformat()
            }
        })

        # Notify teachers with updated student list
        students_list = list(self.rooms_students_info.get(room_id, {}).values())
        await self.broadcast_to_room_teachers(room_id, {
            "type": "student_leave",
            "data": {
                "student_id": student_id,
                "student_name": student_name,
                "students": students_list,  # Send updated list
                "timestamp": datetime.now().isoformat()
            }
        })

    async def disconnect_teacher(self, websocket: WebSocket):
        """
        Disconnect a teacher
        ONLY close room when LAST teacher leaves
        """
        async with self.lock:
            room_id = self.teacher_rooms.get(websocket)

            if not room_id:
                print("⚠️ Teacher disconnect called but no room_id found")
                if websocket in self.teacher_rooms:
                    del self.teacher_rooms[websocket]
                if websocket in self.teacher_names:
                    del self.teacher_names[websocket]
                return

            if room_id in self.rooms_teachers:
                # Remove this specific teacher
                if websocket in self.rooms_teachers[room_id]:
                    self.rooms_teachers[room_id].remove(websocket)
                    teacher_name = self.teacher_names.get(websocket, "Unknown Teacher")
                    print(f"👨‍🏫 Teacher '{teacher_name}' left room {room_id}")

                # Check if this was the LAST teacher
                if len(self.rooms_teachers[room_id]) == 0:
                    print(f"🚪 CLOSING ROOM {room_id} - Last teacher disconnected")

                    # Notify all students that class ended
                    students_to_close = list(self.rooms_students.get(room_id, {}).values())
                    print(f"📢 Notifying {len(students_to_close)} student(s) that class ended")

                    for student_ws in students_to_close:
                        try:
                            await student_ws.send_json({
                                "type": "room_closed",
                                "message": "Teacher has ended the class"
                            })
                            await student_ws.close(code=4003, reason="Room closed")
                        except Exception as e:
                            print(f"❌ Error notifying student: {e}")

                    # Clean up ALL room data
                    if room_id in self.rooms_teachers:
                        del self.rooms_teachers[room_id]
                    if room_id in self.rooms_students:
                        del self.rooms_students[room_id]
                    if room_id in self.rooms_students_info:
                        del self.rooms_students_info[room_id]
                    if room_id in self.room_ids:
                        del self.room_ids[room_id]
                    # FIXED: Remove from used codes when room is completely closed
                    if room_id in self.used_room_codes:
                        self.used_room_codes.remove(room_id)
                        print(f"♻️ Room code {room_id} released for reuse")

                    print(f"✅ Room {room_id} completely cleaned up")

            # Clean up teacher mappings
            if websocket in self.teacher_rooms:
                del self.teacher_rooms[websocket]
            if websocket in self.teacher_names:
                del self.teacher_names[websocket]

    async def broadcast_to_room_teachers(self, room_id: str, message: dict):
        """Broadcast message to all teachers in a room"""
        if room_id not in self.rooms_teachers:
            print(f"⚠️ No teachers in room {room_id} to broadcast to")
            return

        disconnected = []
        teacher_count = len(self.rooms_teachers[room_id])
        
        for teacher_ws in self.rooms_teachers[room_id]:
            try:
                await teacher_ws.send_json(message)
            except Exception as e:
                print(f"❌ Error sending to teacher in room {room_id}: {e}")
                disconnected.append(teacher_ws)

        # Clean up disconnected teachers
        for teacher_ws in disconnected:
            await self.disconnect_teacher(teacher_ws)

        if teacher_count > 0:
            print(f"📤 Broadcast to {teacher_count} teacher(s) in room {room_id}: {message['type']}")

    async def broadcast_to_room_students(self, room_id: str, message: dict, exclude_id: str = None):
        """Broadcast message to all students in a room"""
        if room_id not in self.rooms_students:
            print(f"⚠️ No students in room {room_id} to broadcast to")
            return

        disconnected = []
        sent_count = 0

        for student_id, student_ws in self.rooms_students[room_id].items():
            if exclude_id and student_id == exclude_id:
                continue

            try:
                await student_ws.send_json(message)
                sent_count += 1
            except Exception as e:
                print(f"❌ Error sending to student {student_id[:8]}... in room {room_id}: {e}")
                disconnected.append(student_id)

        # Clean up disconnected students
        for student_id in disconnected:
            await self.disconnect_student(room_id, student_id)

        if sent_count > 0:
            print(f"📤 Broadcast to {sent_count} student(s) in room {room_id}: {message['type']}")

    async def update_student_attention(self, room_id: str, student_id: str, attention_data: dict):
        """Update student's attention status and notify teachers"""
        async with self.lock:
            if room_id in self.rooms_students_info and student_id in self.rooms_students_info[room_id]:
                student_info = self.rooms_students_info[room_id][student_id]
                student_info["status"] = attention_data.get("status", "attentive")
                student_info["last_update"] = datetime.now().isoformat()

        # Broadcast to teachers
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
                print(f"📤 Sent to student {student_id[:8]}...: {message['type']}")
            except Exception as e:
                print(f"❌ Error sending to student {student_id[:8]}...: {e}")

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
        if exists:
            print(f"✅ Room {room_id} exists with {len(self.rooms_teachers[room_id])} teacher(s)")
        else:
            print(f"❌ Room {room_id} does not exist or has no teachers")
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
print("✅ Global ConnectionManager instance created")
print("=" * 60)