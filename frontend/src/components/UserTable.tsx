import { useAuth } from '@/context/AuthContext';
import { User } from '@/types/api';
import { getCompanyUsers } from '@/utils/api';
import Table, { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';

interface UserTableProps {
  /** Compact preview mode for the dashboard: paginated, fewer columns. */
  compact?: boolean;
}

export function UserTable({ compact = false }: UserTableProps) {
  const { isAuthenticated } = useAuth();

  const [loading, setLoading] = useState<boolean>(false);
  const [users, setUsers] = useState<any>([]);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const res = await getCompanyUsers({ page: 1, limit: 100 });
      setUsers(res.data?.items);
    } catch (error) {
      console.error('Fetch users error', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isAuthenticated) return;
    fetchUsers();
  }, []);

  const columns: ColumnsType<User> = [
    {
      title: 'Email',
      dataIndex: 'email',
      key: 'email',
      render: (text) => <span style={{ fontWeight: 500 }}>{text}</span>,
    },
    ...(compact
      ? []
      : [
          {
            title: 'Phone',
            dataIndex: 'phone',
            key: 'phone',
          } as { title: string; dataIndex: string; key: string },
        ]),
    {
      title: 'Name',
      dataIndex: 'first_name',
      key: 'first_name',
      render: (_: string, record: User) =>
        [record.first_name, record.last_name].filter(Boolean).join(' ') || '-',
    },
    {
      title: 'Role',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => role || '-',
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => status || '-',
    },
  ];

  return (
    <>
      <Table
        columns={columns}
        dataSource={users}
        loading={loading}
        rowKey='id'
        size={compact ? 'small' : 'middle'}
        pagination={
          compact
            ? { pageSize: 5, hideOnSinglePage: true, showSizeChanger: false }
            : false
        }
      />
    </>
  );
}
