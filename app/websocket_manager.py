from fastapi import WebSocket
from typing import Dict, List
import logging
from datetime import datetime
import random
import string

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Room management
        self.rooms_teachers: Dict[str, List[WebSocket]] = {}
        self.rooms_students: Dict[str, Dict[str, WebSocket]] = {}
        self.rooms_students_info: Dict[str, Dict[str, dict]] = {}
        
        # Reverse lookup
        self.teacher_to_room: Dict[WebSocket, str] = {}
        self.student_to_room: Dict[str, str] = {}
    
    def generate_room_id(self) -> str:
        """Generate a unique 6-character room code"""
        while True:
            room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if room_id not in self.rooms_teachers:
                return room_id
    
    async def connect_teacher(self, websocket: WebSocket, name: str) -> str:
        """Connect teacher and create a new room"""
        await websocket.accept()
        
        room_id = self.generate_room_id()
        
        if room_id not in self.rooms_teachers:
            self.rooms_teachers[room_id] = []
            self.rooms_students[room_id] = {}
            self.rooms_students_info[room_id] = {}
        
        self.rooms_teachers[room_id].append(websocket)
        self.teacher_to_room[websocket] = room_id
        
        logger.info(f"✅ Teacher connected to room {room_id}")
        return room_id
    
    async def connect_student(self, websocket: WebSocket, room_id: str, student_id: str, name: str) -> bool:
        """Connect student to a room"""
        if room_id not in self.rooms_teachers:
            logger.error(f"❌ Room {room_id} does not exist")
            return False
        
        await websocket.accept()
        
        if room_id not in self.rooms_students:
            self.rooms_students[room_id] = {}
            self.rooms_students_info[room_id] = {}
        
        self.rooms_students[room_id][student_id] = websocket
        self.rooms_students_info[room_id][student_id] = {
            'id': student_id,
            'name': name,
            'status': 'attentive',
            'last_update': datetime.now().isoformat()
        }
        self.student_to_room[student_id] = room_id
        
        # Notify teacher
        await self.broadcast_to_room_teachers(room_id, {
            'type': 'student_join',
            'data': {
                'student_id': student_id,
                'student_name': name,
                'timestamp': datetime.now().isoformat()
            }
        })
        
        logger.info(f"✅ Student {name} connected to room {room_id}")
        return True
    
    def room_exists(self, room_id: str) -> bool:
        """Check if room exists"""
        return room_id in self.rooms_teachers
    
    async def disconnect_teacher(self, websocket: WebSocket):
        """Disconnect teacher and close room"""
        room_id = self.teacher_to_room.get(websocket)
        if not room_id:
            return
        
        # Notify all students
        if room_id in self.rooms_students:
            await self.broadcast_to_room_students(room_id, {
                'type': 'room_closed',
                'data': {'message': 'Teacher ended the class'}
            })
        
        # Cleanup
        if room_id in self.rooms_teachers:
            self.rooms_teachers[room_id] = [ws for ws in self.rooms_teachers[room_id] if ws != websocket]
            if not self.rooms_teachers[room_id]:
                del self.rooms_teachers[room_id]
                if room_id in self.rooms_students:
                    del self.rooms_students[room_id]
                if room_id in self.rooms_students_info:
                    del self.rooms_students_info[room_id]
        
        if websocket in self.teacher_to_room:
            del self.teacher_to_room[websocket]
        
        logger.info(f"❌ Teacher disconnected from room {room_id}")
    
    async def disconnect_student(self, room_id: str, student_id: str):
        """Disconnect student from room"""
        if room_id in self.rooms_students and student_id in self.rooms_students[room_id]:
            del self.rooms_students[room_id][student_id]
        
        if room_id in self.rooms_students_info and student_id in self.rooms_students_info[room_id]:
            student_name = self.rooms_students_info[room_id][student_id]['name']
            del self.rooms_students_info[room_id][student_id]
            
            # Notify teacher
            await self.broadcast_to_room_teachers(room_id, {
                'type': 'student_leave',
                'data': {
                    'student_id': student_id,
                    'student_name': student_name,
                    'timestamp': datetime.now().isoformat()
                }
            })
        
        if student_id in self.student_to_room:
            del self.student_to_room[student_id]
        
        logger.info(f"❌ Student {student_id} disconnected from room {room_id}")
    
    async def broadcast_to_room_teachers(self, room_id: str, message: dict):
        """Send message to all teachers in room"""
        if room_id not in self.rooms_teachers:
            return
        
        dead_connections = []
        for websocket in self.rooms_teachers[room_id]:
            try:
                await websocket.send_json(message)
            except:
                dead_connections.append(websocket)
        
        for ws in dead_connections:
            await self.disconnect_teacher(ws)
    
    async def broadcast_to_room_students(self, room_id: str, message: dict):
        """Send message to all students in room"""
        if room_id not in self.rooms_students:
            return
        
        dead_connections = []
        for student_id, websocket in self.rooms_students[room_id].items():
            try:
                await websocket.send_json(message)
            except:
                dead_connections.append(student_id)
        
        for student_id in dead_connections:
            await self.disconnect_student(room_id, student_id)
    
    async def send_to_student(self, room_id: str, student_id: str, message: dict):
        """Send message to specific student"""
        if room_id in self.rooms_students and student_id in self.rooms_students[room_id]:
            try:
                await self.rooms_students[room_id][student_id].send_json(message)
            except:
                await self.disconnect_student(room_id, student_id)
    
    async def broadcast_to_other_students(self, room_id: str, exclude_student_id: str, message: dict):
        """Broadcast to all students except one"""
        if room_id not in self.rooms_students:
            return
        
        for student_id, websocket in self.rooms_students[room_id].items():
            if student_id != exclude_student_id:
                try:
                    await websocket.send_json(message)
                except:
                    pass
    
    async def update_student_attention(self, room_id: str, student_id: str, status_data: dict):
        """Update student attention status"""
        if room_id in self.rooms_students_info and student_id in self.rooms_students_info[room_id]:
            self.rooms_students_info[room_id][student_id].update(status_data)
            self.rooms_students_info[room_id][student_id]['last_update'] = datetime.now().isoformat()
            
            # Broadcast status update to teacher
            await self.broadcast_to_room_teachers(room_id, {
                'type': 'attention_update',
                'data': {
                    'student_id': student_id,
                    'student_name': self.rooms_students_info[room_id][student_id]['name'],
                    'status': status_data.get('status'),
                    'confidence': status_data.get('confidence'),
                    'timestamp': datetime.now().isoformat()
                }
            })
    
    async def broadcast_camera_frame(self, room_id: str, student_id: str, frame_data: str):
        """Broadcast student camera frame to teacher"""
        await self.broadcast_to_room_teachers(room_id, {
            'type': 'camera_frame',
            'data': {
                'student_id': student_id,
                'frame': frame_data
            }
        })

# ✅ THIS LINE IS CRITICAL - IT MUST BE AT THE END
manager = ConnectionManager()