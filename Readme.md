


          
# FP2Pivot App (Fingerspot to OWL)

A web-based application for managing employee data synchronization and PIN-NIK mapping between local database and ERP system.

## Overview

FP2Pivot App is designed to facilitate the management of employee data by providing a seamless interface for synchronizing employee information and mapping PIN (Personal Identification Number) to NIK (Employee Identification Number) relationships.

## Features

### 1. Data Synchronization
- Real-time synchronization with ERP system
- Track total records, updated records, and new entries
- Automatic last sync timestamp tracking
- Visual feedback for sync status

### 2. PIN-NIK Mapping Management
- Interactive interface for mapping employee PINs to NIKs
- Search functionality for both PIN and NIK fields
- Real-time updates with instant feedback
- Filter records by mapping status (set/not set)
- Bulk management capabilities

### 3. User Interface Features
- Responsive data tables with pagination
- Advanced search and filtering capabilities
- Interactive dropdown menus with search functionality
- Toast notifications for operation feedback
- Error handling with user-friendly messages

## Technical Requirements

### Server Requirements
- Python 3.x
- MySQL Database
- Web Server (Apache/Nginx)

### Python Dependencies
```bash
pip install flask
pip install mysql-connector-python
```

### Frontend Dependencies
- jQuery 3.6.0
- DataTables 1.11.5
- Select2 4.1.0
- SweetAlert2
- Bootstrap 5 with custom theme

### Database Setup
Required tables:
- `pegawai`: Stores employee information
- `datakaryawan_owl`: Stores ERP system employee data
- `pin_nik`: Stores PIN-NIK mapping relationships

## Installation

1. Clone the repository to your web server directory:
```bash
cd /path/to/webroot
git clone [repository-url]
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Configure database connection in your configuration file

4. Set up the required database tables

5. Configure web server to serve the Flask application

## Usage

1. Access the application through your web browser
2. Use the Data Synchronization page to sync employee data from ERP
3. Navigate to PIN-NIK Settings to manage PIN-NIK mappings
4. Use filters and search functionality to find specific records
5. Update mappings as needed with real-time feedback

## Browser Support
- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

## Security Considerations
- Implement proper authentication
- Use HTTPS for secure data transmission
- Regular database backups
- Input validation and sanitization

## Contributing
Please read CONTRIBUTING.md for details on our code of conduct and the process for submitting pull requests.

## License
This project is licensed under the MIT License - see the LICENSE.md file for details.

        